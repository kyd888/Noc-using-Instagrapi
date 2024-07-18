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
from botocore.exceptions import NoCredentialsError, ClientError as BotoClientError
from instagrapi.exceptions import ClientError
import openai

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key')  # Replace with a secure key

# Version number
app_version = "1.1.6"

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

# Initialize OpenAI client
openai.api_key = os.environ.get('OPENAI_API_KEY')  # Ensure you have set your OpenAI API key

@app.route('/')
def index():
    return render_template('index.html', version=app_version, csv_data=csv_data_global)

@app.route('/login', methods=['POST'])
def login():
    global client, s3, bucket_name
    insta_username = request.form['insta_username']
    insta_password = request.form['insta_password']
    
    # Read AWS access key from secret file
    with open('/etc/secrets/aws_access_key.txt', 'r') as file:
        aws_access_key = file.read().strip()
    
    # Read AWS secret key from secret file
    with open('/etc/secrets/aws_secret_key.txt', 'r') as file:
        aws_secret_key = file.read().strip()
    
    aws_region = 'us-east-1'
    bucket_name = 'noc-user-data1'
    
    try:
        print(f"Attempting to login with username: {insta_username} (App Version: {app_version})")
        client = Client()
        login_with_retries(client, insta_username, insta_password)
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

def login_with_retries(client, username, password, retries=5, initial_delay=60):
    delay = initial_delay
    for i in range(retries):
        try:
            client.login(username, password)
            return
        except ClientError as e:
            if 'Please wait a few minutes before you try again' in str(e):
                print(f"Rate limit hit during login. Retrying in {delay} seconds. (App Version: {app_version})")
                time.sleep(delay + random.uniform(0, delay / 2))  # Add jitter to delay
                delay *= 2  # Exponential backoff
            else:
                raise e
    raise Exception("Maximum retries reached for login")

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
        except ClientError as e:
            if 'Please wait a few minutes before you try again' in str(e):
                print(f"Rate limit hit. Retrying in {delay} seconds. (App Version: {app_version})")
                time.sleep(delay + random.uniform(0, delay / 2))  # Add jitter to delay
                delay *= 2  # Exponential backoff
            else:
                raise e
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}. Retrying in {delay} seconds. (App Version: {app_version})")
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

def monitor_new_posts(user_id, username):
    global comments_data, monitoring, post_urls, last_refresh_time, refresh_messages, csv_data_global
    last_post_id = None
    cycle_count = 0  # Initialize cycle counter
    interaction_count = 0  # Initialize interaction counter

    while monitoring.get(username, False):
        try:
            latest_post = get_latest_post(user_id)
            interaction_count += 1  # Increment interaction counter
            if latest_post and latest_post.pk != last_post_id:
                last_post_id = latest_post.pk
                post_url = f"https://www.instagram.com/p/{latest_post.code}/"
                unique_id = str(uuid.uuid4().int)[:4]
                post_urls[username].append({'url': post_url, 'id': unique_id})
                print(f"Found new post: {post_url} (App Version: {app_version})")
                comments = get_comments(latest_post.pk, 10)
                # Filter out comments from the target user
                comments = [c for c in comments if c[0] != username]
                interaction_count += 1  # Increment interaction counter
                if comments:
                    comments_data[username].append({'id': unique_id, 'comments': comments})
                    print(f"Stored comments for post {unique_id}: {comments} (App Version: {app_version})")
                    # Write to S3 and store locally
                    csv_data = [{'username': username, 'post_id': unique_id, 'commenter': c[0], 'comment': c[1], 'time': c[2]} for c in comments]
                    csv_data_global.extend(csv_data)
                    write_to_s3(csv_data_global, 'NOC_data.csv')  # Updated to include filename
                    print(f"CSV Data: {csv_data} (App Version: {app_version})")
                    # Analyze comments using OpenAI
                    analyze_comments_with_openai(comments, unique_id)
                else:
                    print(f"No comments found for post {unique_id} (App Version: {app_version})")
                last_refresh_time[username] = time.strftime('%Y-%m-%d %H:%M:%S')
            sleep_interval = random.randint(30, 60)  # Reduced interval between 30 to 60 seconds
            print(f"Sleeping for {sleep_interval} seconds. (App Version: {app_version})")
            time.sleep(sleep_interval)
            cycle_count += 1  # Increment cycle counter

            for post in post_urls[username]:
                post_code = post['url'].split('/')[-2]
                try:
                    post_media_id = client.media_pk_from_code(post_code)
                    new_comments = get_comments(post_media_id, 10)
                    # Filter out comments from the target user
                    new_comments = [c for c in new_comments if c[0] != username]
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
                        write_to_s3(csv_data_global, 'NOC_data3.csv')  # Updated to include filename
                        print(f"CSV Data: {csv_data} (App Version: {app_version})")
                    else:
                        print(f"No new comments found for post {post['id']} (App Version: {app_version})")
                except Exception as e:
                    if 'Please wait a few minutes before you try again' in str(e):
                        print(f"Rate limit hit. Waiting for {break_duration // 60} minutes. (App Version: {app_version})")
                        time.sleep(break_duration)
                    else:
                        print(f"Error fetching media ID for post code {post_code}: {e} (App Version: {app_version})")

            if interaction_count >= break_after_actions:
                print(f"Taking a break for {break_duration // 60} minutes to avoid being flagged. (App Version: {app_version})")
                time.sleep(break_duration)  # Sleep for the break duration
                interaction_count = 0  # Reset interaction counter after the break
        except Exception as e:
            print(f"An error occurred in the monitoring loop: {e} (App Version: {app_version})")

    monitoring[username] = False  # Stop monitoring after reaching max cycles or interactions
    print(f"Monitoring stopped for {username} after {cycle_count} cycles and {interaction_count} interactions. (App Version: {app_version})")

def analyze_comments_with_openai(comments, unique_id):
    try:
        comment_texts = [comment[1] for comment in comments]
        joined_comments = " ".join(comment_texts)
        response = openai.Completion.create(
            engine="davinci",
            prompt=f"Analyze the following comments and summarize the main topics discussed:\n\n{joined_comments}",
            max_tokens=150
        )
        summary = response.choices[0].text.strip()
        print(f"AI Analysis for post {unique_id}: {summary} (App Version: {app_version})")
        # Save the summary to S3 or display it as needed
        # Example: write_to_s3([{'post_id': unique_id, 'summary': summary}], 'NOC_analysis.csv')
    except Exception as e:
        print(f"Error during AI analysis: {e} (App Version: {app_version})")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # Use the PORT environment variable provided by Render
    app.run(host='0.0.0.0', port=port, debug=False)
