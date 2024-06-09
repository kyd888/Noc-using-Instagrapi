import os
import time
import random
import uuid
import pandas as pd
from flask import Flask, render_template, request, jsonify, session
from instagrapi import Client
from threading import Thread
import requests
import boto3
from io import StringIO
from botocore.exceptions import NoCredentialsError

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key')  # Replace with a secure key

# Version number
app_version = "1.1.3"

client = None  # Store the client for the single account
s3 = None  # Store the S3 client
bucket_name = None
monitoring = {}
comments_data = {}
post_urls = {}
last_refresh_time = {}
refresh_messages = {}
csv_data_global = []  # Store the CSV data to display on the web page
max_cycles = 100  # Set a maximum number of monitoring cycles
max_interactions = 50  # Set a maximum number of interactions per session
break_after_actions = 20  # Take a break after this many actions
break_duration = 1800  # Break duration in seconds (30 minutes)

@app.route('/')
def index():
    return render_template('index.html', version=app_version, csv_data=csv_data_global)

@app.route('/login', methods=['POST'])
def login():
    global client, s3, bucket_name
    insta_username = request.form['insta_username']
    insta_password = request.form['insta_password']
    aws_access_key = request.form['aws_access_key']
    aws_secret_key = request.form['aws_secret_key']
    aws_region = request.form['aws_region']
    bucket_name = request.form['s3_bucket_name']
    try:
        print(f"Attempting to login with username: {insta_username} (App Version: {app_version})")
        client = Client()
        client.login(insta_username, insta_password)
        session['logged_in'] = True
        # Configure AWS S3 client
        s3 = boto3.client('s3', 
            aws_access_key_id=aws_access_key, 
            aws_secret_access_key=aws_secret_key, 
            region_name=aws_region
        )
        return jsonify({'status': 'Login successful', 'version': app_version})
    except Exception as e:
        print(f"Login failed: {e} (App Version: {app_version})")
        return jsonify({'status': f'Login failed: {str(e)}', 'version': app_version})

@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    if not session.get('logged_in'):
        return jsonify({'status': 'Please login first', 'version': app_version}), 403

    global monitoring, post_urls, last_refresh_time, refresh_messages, comments_data
    target_usernames = request.form.get('target_usernames')
    if not target_usernames:
        return jsonify({'status': 'No target usernames provided', 'version': app_version}), 400

    target_usernames = target_usernames.split(',')  # List of usernames
    for username in target_usernames:
        username = username.strip()
        user_id = search_user(username)
        if user_id is None:
            return jsonify({'status': f'User {username} not found or error occurred', 'version': app_version}), 404

        monitoring[username] = True
        refresh_messages[username] = []
        comments_data[username] = []
        post_urls[username] = []
        last_refresh_time[username] = None
        thread = Thread(target=monitor_new_posts, args=(user_id, username))
        thread.start()
    
    return jsonify({'status': 'Monitoring started', 'version': app_version})

@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    global monitoring
    monitoring = {key: False for key in monitoring}
    return jsonify({'status': 'Monitoring stopped', 'version': app_version})

@app.route('/get_comments', methods=['GET'])
def get_comments_data():
    return jsonify({'comments': comments_data, 'version': app_version})

@app.route('/get_post_urls', methods=['GET'])
def get_post_urls():
    return jsonify({
        'post_urls': post_urls, 
        'last_refresh_time': last_refresh_time, 
        'refresh_messages': {user: msgs[0] if msgs else '' for user, msgs in refresh_messages.items()},  # Get the latest message per user
        'version': app_version
    })

def retry_with_exponential_backoff(func, retries=5, initial_delay=1):
    delay = initial_delay
    for i in range(retries):
        try:
            return func()
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}. Retrying in {delay} seconds. (App Version: {app_version})")
            time.sleep(delay)
            delay *= 2
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
    posts = client.user_medias(user_id, amount=1)
    if posts:
        print(f"Latest post ID: {posts[0].pk} (App Version: {app_version})")
    else:
        print("No posts found. (App Version: {app_version})")
    return posts[0] if posts else None

def get_comments(media_id, count=10):
    try:
        comments = client.media_comments(media_id, amount=count)
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
        s3.put_object(Bucket=bucket_name, Key=filename, Body=csv_buffer.getvalue())
        print(f"Data written to S3 bucket {bucket_name} (App Version: {app_version})")
    except NoCredentialsError:
        print("Credentials not available")

def monitor_new_posts(user_id, username):
    global comments_data, monitoring, post_urls, last_refresh_time, refresh_messages, csv_data_global
    last_post_id = None
    cycle_count = 0  # Initialize cycle counter
    interaction_count = 0  # Initialize interaction counter

    while monitoring.get(username, False) and cycle_count < max_cycles and interaction_count < max_interactions:
        latest_post = get_latest_post(user_id)
        interaction_count += 1  # Increment interaction counter
        if latest_post and latest_post.pk != last_post_id:
            last_post_id = latest_post.pk
            post_url = f"https://www.instagram.com/p/{latest_post.code}/"
            unique_id = str(uuid.uuid4().int)[:4]
            post_urls[username].append({'url': post_url, 'id': unique_id})
            print(f"Found new post: {post_url} (App Version: {app_version})")
            comments = get_comments(latest_post.pk, 10)
            interaction_count += 1  # Increment interaction counter
            if comments:
                comments_data[username].append({'id': unique_id, 'comments': comments})
                print(f"Stored comments for post {unique_id}: {comments} (App Version: {app_version})")
                # Write to S3 and store locally
                csv_data = [{'username': username, 'post_id': unique_id, 'commenter': c[0], 'comment': c[1], 'time': c[2]} for c in comments]
                csv_data_global.extend(csv_data)
                write_to_s3(csv_data, 'instagram_data.csv')  # Updated to include filename
                print(f"CSV Data: {csv_data} (App Version: {app_version})")
            else:
                print(f"No comments found for post {unique_id} (App Version: {app_version})")
            last_refresh_time[username] = time.strftime('%Y-%m-%d %H:%M:%S')
        sleep_interval = random.randint(60, 120)  # Randomize interval between 60 to 120 seconds
        print(f"Sleeping for {sleep_interval} seconds. (App Version: {app_version})")
        time.sleep(sleep_interval)
        cycle_count += 1  # Increment cycle counter

        for post in post_urls[username]:
            post_code = post['url'].split('/')[-2]
            try:
                post_media_id = client.media_pk_from_code(post_code)
                new_comments = get_comments(post_media_id, 10)
                interaction_count += 1  # Increment interaction counter
                if new_comments:
                    # Ensure we maintain the structure of the comments data
                    for post_data in comments_data[username]:
                        if post_data['id'] == post['id']:
                            post_data['comments'] = new_comments
                            break
                    refresh_message = f"Refreshing comments for post {post['id']} at {time.strftime('%Y-%m-%d %H:%M:%S')} (App Version: {app_version})"
                    refresh_messages[username].clear()
                    refresh_messages[username].append(refresh_message)
                    print(refresh_message)
                    # Write to S3 and store locally
                    csv_data = [{'username': username, 'post_id': post['id'], 'commenter': c[0], 'comment': c[1], 'time': c[2]} for c in new_comments]
                    csv_data_global.extend(csv_data)
                    write_to_s3(csv_data, 'instagram_data.csv')  # Updated to include filename
                    print(f"CSV Data: {csv_data} (App Version: {app_version})")
                else:
                    print(f"No new comments found for post {post['id']} (App Version: {app_version})")
            except Exception as e:
                print(f"Error fetching media ID for post code {post_code}: {e} (App Version: {app_version})")

        if interaction_count >= break_after_actions:
            print(f"Taking a break for {break_duration // 60} minutes to avoid being flagged. (App Version: {app_version})")
            time.sleep(break_duration)  # Sleep for the break duration
            interaction_count = 0  # Reset interaction counter after the break

    monitoring[username] = False  # Stop monitoring after reaching max cycles or interactions
    print(f"Monitoring stopped for {username} after {cycle_count} cycles and {interaction_count} interactions. (App Version: {app_version})")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
