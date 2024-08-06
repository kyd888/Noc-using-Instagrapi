import os
import time
import random
import json
import uuid
import boto3
import pandas as pd
from io import StringIO
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from instagrapi import Client
from instagrapi.exceptions import JSONDecodeError
from botocore.exceptions import NoCredentialsError, ClientError as BotoClientError
from transformers import pipeline

app = Flask(__name__)

# AWS S3 configuration
s3 = boto3.client('s3')
bucket_name = 'your-s3-bucket-name'

# Global variables
client = Client()
client.login('your_instagram_username', 'your_instagram_password')
monitoring = {}
last_refresh_time = {}
refresh_messages = {}
csv_data_global = []
next_cycle_time = time.time()
commenters_interests = {}

# Constants
app_version = "1.1.6"
break_after_actions = 10
long_break_probability = 0.1
long_break_duration = 3600
break_duration = 600

@app.route('/')
def index():
    return render_template('index.html', version=app_version, csv_data=csv_data_global, commenters_interests=commenters_interests)

@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    username = request.form['username']
    monitoring[username] = True
    user_id = search_user(username)
    if user_id:
        last_refresh_time[username] = time.strftime('%Y-%m-%d %H:%M:%S')
        post_monitoring_loop(user_id, username)
    return jsonify({"status": "Monitoring started for user: {}".format(username)})

@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    username = request.form['username']
    monitoring[username] = False
    return jsonify({"status": "Monitoring stopped for user: {}".format(username)})

@app.route('/get_post_urls', methods=['GET'])
def get_post_urls():
    global next_cycle_time
    return jsonify({'post_urls': post_urls, 'seconds_until_next_cycle': int(next_cycle_time - time.time())})

def retry_with_exponential_backoff(func, initial_delay=1, max_delay=60, max_retries=5):
    delay = initial_delay
    for _ in range(max_retries):
        try:
            return func()
        except ValueError as e:
            print(f"JSON decode error: {e}. Retrying in {delay} seconds. (App Version: {app_version})")
            time.sleep(delay + random.uniform(0, delay / 2))  # Add jitter to delay
            delay *= 2  # Exponential backoff
        except JSONDecodeError as e:
            print(f"JSONDecodeError: {e}. Retrying in {delay} seconds. (App Version: {app_version})")
            time.sleep(delay + random.uniform(0, delay / 2))
            delay *= 2
        except Exception as e:
            print(f"Unexpected error: {e}. Retrying in {delay} seconds. (App Version: {app_version})")
            time.sleep(delay + random.uniform(0, delay / 2))  # Add jitter to delay
            delay *= 2  # Exponential backoff
    raise Exception("Maximum retries reached")

def get_user_id_with_retry(username):
    return retry_with_exponential_backoff(lambda: client.user_id_from_username(username))

def search_user(username):
    try:
        user_id = get_user_id_with_retry(username)
        print(f"User ID for {username} is {user_id} (App Version: {app_version})")
        return user_id
    except Exception as e:
        print(f"Error fetching user ID for {username}: {e} (App Version: {app_version})")
        return None

def get_latest_post(user_id):
    try:
        posts = retry_with_exponential_backoff(lambda: client.user_medias(user_id, amount=1))
        if posts:
            print(f"Latest post ID: {posts[0].pk} (App Version: {app_version})")
        else:
            print("No posts found. (App Version: {app_version})")
        return posts[0] if posts else None
    except JSONDecodeError as e:
        print(f"JSONDecodeError: {e} (App Version: {app_version})")
        return None
    except Exception as e:
        print(f"Error fetching latest post for user ID {user_id}: {e} (App Version: {app_version})")
        return None

def get_comments(media_id, count=10):  # Fetch 10 comments each cycle
    try:
        comments = retry_with_exponential_backoff(lambda: client.media_comments(media_id, amount=count))
        if comments:
            comments_data = [
                (comment.user.username, comment.text, comment.created_at if hasattr(comment, 'created_at') else 'N/A')
                for comment in comments
            ]
            print(f"Fetched {len(comments_data)} comments for media ID {media_id} (App Version: {app_version})")
            return comments_data
        else:
            print(f"No comments found for media ID {media_id} (App Version: {app_version})")
            return []
    except Exception as e:
        print(f"Error fetching comments for media ID {media_id}: {e} (App Version: {app_version})")
        return []

def write_to_s3(data, filename):
    df = pd.DataFrame(data)
    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    try:
        print(f"Attempting to write data to S3 bucket {bucket_name} (App Version: {app_version})")
        print(f"Data being written:\n{df}")  # Log the data being written
        s3.put_object(Bucket=bucket_name, Key=filename, Body=csv_buffer.getvalue())
        print(f"Data written to S3 bucket {bucket_name} (App Version: {app_version})")
    except NoCredentialsError:
        print("Credentials not available")
    except BotoClientError as e:
        print(f"Boto Client Error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

def post_monitoring_loop(user_id, username):
    global monitoring, last_refresh_time, refresh_messages, csv_data_global, next_cycle_time
    last_post_id = None
    cycle_count = 0
    interaction_count = 0

    while monitoring.get(username, False):
        try:
            latest_post, post_url, unique_id = scan_for_new_post(user_id, last_post_id, username)
            if latest_post:
                last_post_id = latest_post.pk
                interaction_count += 1
                handle_new_post(username, post_url, unique_id, latest_post.pk)
                last_refresh_time[username] = time.strftime('%Y-%m-%d %H:%M:%S')

            sleep_interval = random.randint(1800, 3600)  # Increase sleep interval to 30-60 minutes
            next_cycle_time = time.time() + sleep_interval
            print(f"Sleeping for {sleep_interval} seconds. (App Version: {app_version})")
            time.sleep(sleep_interval)
            cycle_count += 1

            if interaction_count >= break_after_actions:
                if random.random() < long_break_probability:
                    print(f"Taking a long break for {long_break_duration // 60} minutes to avoid being flagged. (App Version: {app_version})")
                    time.sleep(long_break_duration)
                else:
                    print(f"Taking a break for {break_duration // 60} minutes to avoid being flagged. (App Version: {app_version})")
                    time.sleep(break_duration)
                interaction_count = 0

        except Exception as e:
            print(f"An error occurred in the monitoring loop: {e} (App Version: {app_version})")

    monitoring[username] = False
    print(f"Monitoring stopped for {username} after {cycle_count} cycles and {interaction_count} interactions. (App Version: {app_version})")

def scan_for_new_post(user_id, last_post_id, username):
    latest_post = get_latest_post(user_id)
    if (latest_post and latest_post.pk != last_post_id):
        post_url = f"https://www.instagram.com/p/{latest_post.code}/"
        unique_id = str(uuid.uuid4().int)[:4]
        post_urls[username].append({'url': post_url, 'id': unique_id})
        print(f"Found new post: {post_url} (App Version: {app_version})")
        return latest_post, post_url, unique_id
    return None, None, None

def handle_new_post(username, post_url, unique_id, media_id):
    global comments_data, csv_data_global, commenters_interests
    new_comments = get_comments(media_id, 10)  # Get 10 new comments
    new_comments = [c for c in new_comments if c[0] != username]
    if new_comments:
        if username not in comments_data:
            comments_data[username] = []
        comments_data[username].extend(new_comments)  # Append new comments
        print(f"Stored new comments for post {unique_id}: {new_comments} (App Version: {app_version})")
        new_csv_data = [{'username': username, 'post_url': post_url, 'unique_id': unique_id,
                         'commenter': comment[0], 'comment': comment[1], 'comment_time': comment[2]} for comment in new_comments]
        csv_data_global.extend(new_csv_data)
        csv_filename = f"{username}_comments.csv"
        write_to_s3(csv_data_global, csv_filename)
        analyze_commenters(new_comments)

def analyze_commenters(comments):
    global commenters_interests
    sentiment_analysis = pipeline('sentiment-analysis')

    for commenter, comment, _ in comments:
        try:
            user_id = get_user_id_with_retry(commenter)
            user_info = client.user_info(user_id)
            num_posts_to_analyze = 2  # Analyze up to 2 posts per commenter

            if user_info.media_count < num_posts_to_analyze:
                print(f"Skipping {commenter} due to insufficient posts for analysis. (App Version: {app_version})")
                continue

            posts = client.user_medias(user_id, num_posts_to_analyze)
            interests = []
            for post in posts:
                caption = post.caption_text
                if caption:
                    analysis = sentiment_analysis(caption)
                    interests.append(analysis)

            commenters_interests[commenter] = interests
            print(f"Analyzed interests for {commenter}: {interests} (App Version: {app_version})")

        except Exception as e:
            print(f"Error analyzing commenter {commenter}: {e} (App Version: {app_version})")

def get_user_profile(username):
    try:
        user_id = client.user_id_from_username(username)
        user_info = client.user_info(user_id)
        profile_data = {
            'username': username,
            'full_name': user_info.full_name,
            'biography': user_info.biography,
            'follower_count': user_info.follower_count,
            'following_count': user_info.following_count,
            'posts': []
        }

        medias = client.user_medias(user_id, 10)  # Fetch latest 10 posts
        for media in medias:
            try:
                media_url = media.thumbnail_url if media.media_type == 1 else media.resources[0].thumbnail_url
            except (IndexError, AttributeError) as e:
                print(f"Error processing media post: {e}")
                continue  # Skip this media post if there's an error

            post = {
                'id': media.pk,
                'caption': media.caption_text,
                'media_type': media.media_type,
                'media_url': str(media_url),
                'timestamp': media.taken_at.isoformat() if isinstance(media.taken_at, datetime) else str(media.taken_at),
                'likes': media.like_count,
                'comments': media.comment_count
            }
            profile_data['posts'].append(post)

        return profile_data
    except Exception as e:
        print(f"An error occurred while fetching data for {username}: {e}")
        return None

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # Use the PORT environment variable provided by Render
    app.run(host='0.0.0.0', port=port)
