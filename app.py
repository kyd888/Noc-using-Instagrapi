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
long_break_probability = 0.1  # Probability of taking a longer break
long_break_duration = 7200  # Longer break duration in seconds (2 hours)
next_cycle_time = None  # Initialize next_cycle_time

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
    bucket_name = 'noc-user-data1'  # Ensure this bucket exists in your AWS account
    
    try:
        print(f"Attempting to login with username: {insta_username} (App Version: {app_version})")
        client = Client()

        # Set device settings to simulate an iPhone 12 Pro
        client.set_device({
            "manufacturer": "Apple",
            "model": "iPhone12,3",
            "device": "d75f3509-4827-4f5e-9431-fd5b60c42305",
            "app_version": "153.0.0.34.96",
            "android_version": 29,
            "android_release": "10",
            "dpi": "440dpi",
            "resolution": "1080x2340",
            "cpu": "apple",
            "version_code": "222826132",
            "device_guid": str(uuid.uuid4())
        })

        # Debugging: Print the device settings
        print(f"Device settings: {client.device}")

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
    global next_cycle_time
    if not session.get('logged_in'):
        return jsonify({'status': 'Please login first', 'version': app_version}), 403

    target_usernames = request.form.get('target_usernames')
    if not target_usernames:
        return jsonify({'status': 'No target usernames provided', 'version': app_version}), 400

    target_usernames = target_usernames.split(',')  # List of usernames
    for username in target_usernames:
        username = username.strip()
        user_id = search_user(username)
        if user_id is None:
            return jsonify({'status': f'User {username} not found or error occurred', 'version': app_version}), 404

        start_monitoring_for_user(user_id, username)
    
    # Set the initial value for the next cycle time
    next_cycle_time = time.time() + random.randint(1800, 3600)
    
    return jsonify({'status': 'Monitoring started', 'version': app_version})

def start_monitoring_for_user(user_id, username):
    global monitoring, post_urls, last_refresh_time, refresh_messages, comments_data
    monitoring[username] = True
    refresh_messages[username] = []
    comments_data[username] = []
    post_urls[username] = []
    last_refresh_time[username] = None
    thread = Thread(target=post_monitoring_loop, args=(user_id, username))
    thread.start()

@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    global monitoring
    monitoring = {key: False for key in monitoring}
    return jsonify({'status': 'Monitoring stopped', 'version': app_version})

@app.route('/get_comments', methods=['GET'])
def get_comments_data():
    global comments_data
    print(f"Comments data being sent to front-end: {comments_data}")
    return jsonify({'comments': comments_data, 'version': app_version})

@app.route('/get_post_urls', methods=['GET'])
def get_post_urls():
    global next_cycle_time
    current_time = time.time()
    seconds_until_next_cycle = max(0, int(next_cycle_time - current_time)) if next_cycle_time else 0
    return jsonify({
        'post_urls': post_urls, 
        'last_refresh_time': last_refresh_time, 
        'refresh_messages': {user: msgs[0] if msgs else '' for user, msgs in refresh_messages.items()},  # Get the latest message per user
        'seconds_until_next_cycle': seconds_until_next_cycle,
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
        except ValueError as e:
            print(f"JSON decode error: {e}. Retrying in {delay} seconds. (App Version: {app_version})")
            time.sleep(delay + random.uniform(0, delay / 2))  # Add jitter to delay
            delay *= 2  # Exponential backoff
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
            return posts[0].pk
        return None
    except Exception as e:
        print(f"Error fetching latest post: {e} (App Version: {app_version})")
        return None

def comment_on_post(post_id, message):
    try:
        retry_with_exponential_backoff(lambda: client.media_comment(post_id, message))
        print(f"Commented on post {post_id} with message: {message} (App Version: {app_version})")
    except Exception as e:
        print(f"Error commenting on post {post_id}: {e} (App Version: {app_version})")

def store_csv_in_s3(file_name, csv_data):
    try:
        csv_buffer = StringIO()
        csv_data.to_csv(csv_buffer)
        csv_content = csv_buffer.getvalue()
        s3.put_object(Bucket=bucket_name, Key=file_name, Body=csv_content)
        print(f"CSV data uploaded to S3 bucket {bucket_name} with file name {file_name} (App Version: {app_version})")
    except (NoCredentialsError, BotoClientError) as e:
        print(f"Error uploading CSV to S3: {e} (App Version: {app_version})")

def fetch_and_store_comments(user_id, username, post_id):
    global comments_data
    try:
        comments = retry_with_exponential_backoff(lambda: client.media_comments(post_id))
        for comment in comments:
            comment_data = {
                'user_id': user_id,
                'username': username,
                'post_id': post_id,
                'comment_id': comment.pk,
                'comment_text': comment.text,
                'comment_time': comment.created_at.strftime('%Y-%m-%d %H:%M:%S')
            }
            comments_data[username].append(comment_data)
        df = pd.DataFrame(comments_data[username])
        if not df.empty:
            csv_file_name = f"{username}_comments_{int(time.time())}.csv"
            store_csv_in_s3(csv_file_name, df)
    except Exception as e:
        print(f"Error fetching comments for post {post_id}: {e} (App Version: {app_version})")

def fetch_new_comments(user_id, username, post_id, last_comment_id=None):
    global comments_data
    try:
        comments = retry_with_exponential_backoff(lambda: client.media_comments(post_id))
        new_comments = []
        for comment in comments:
            if last_comment_id is None or comment.pk > last_comment_id:
                new_comment = {
                    'user_id': user_id,
                    'username': username,
                    'post_id': post_id,
                    'comment_id': comment.pk,
                    'comment_text': comment.text,
                    'comment_time': comment.created_at.strftime('%Y-%m-%d %H:%M:%S')
                }
                comments_data[username].append(new_comment)
                new_comments.append(new_comment)
        if new_comments:
            df = pd.DataFrame(new_comments)
            if not df.empty:
                csv_file_name = f"{username}_new_comments_{int(time.time())}.csv"
                store_csv_in_s3(csv_file_name, df)
        return new_comments
    except Exception as e:
        print(f"Error fetching new comments for post {post_id}: {e} (App Version: {app_version})")
        return []

def generate_comment_text(username):
    try:
        response = openai.Completion.create(
            model="text-davinci-002",
            prompt=f"Generate an engaging and personalized comment for {username}'s latest Instagram post:",
            temperature=0.7,
            max_tokens=50
        )
        comment_text = response.choices[0].text.strip()
        print(f"Generated comment for {username}: {comment_text} (App Version: {app_version})")
        return comment_text
    except Exception as e:
        print(f"Error generating comment for {username}: {e} (App Version: {app_version})")
        return "Great post!"

def like_post(post_id):
    try:
        retry_with_exponential_backoff(lambda: client.media_like(post_id))
        print(f"Liked post {post_id} (App Version: {app_version})")
    except Exception as e:
        print(f"Error liking post {post_id}: {e} (App Version: {app_version})")

def follow_user(user_id):
    try:
        retry_with_exponential_backoff(lambda: client.user_follow(user_id))
        print(f"Followed user {user_id} (App Version: {app_version})")
    except Exception as e:
        print(f"Error following user {user_id}: {e} (App Version: {app_version})")

def post_monitoring_loop(user_id, username):
    global max_cycles, max_interactions, break_after_actions, long_break_probability, long_break_duration, next_cycle_time
    cycle = 0
    while monitoring.get(username) and cycle < max_cycles:
        post_id = get_latest_post(user_id)
        if post_id is None:
            continue

        if post_id not in post_urls[username]:
            post_urls[username].append(post_id)
            comment_text = generate_comment_text(username)
            comment_on_post(post_id, comment_text)
            like_post(post_id)
            follow_user(user_id)
            fetch_and_store_comments(user_id, username, post_id)
            cycle += 1

            if cycle % break_after_actions == 0:
                if random.random() < long_break_probability:
                    print(f"Taking a long break for {long_break_duration} seconds. (App Version: {app_version})")
                    time.sleep(long_break_duration)
                else:
                    short_break_duration = random.randint(300, 600)  # Short break between 5 to 10 minutes
                    print(f"Taking a short break for {short_break_duration} seconds. (App Version: {app_version})")
                    time.sleep(short_break_duration)

        if len(post_urls[username]) > max_interactions:
            post_urls[username].pop(0)

        last_comment_id = comments_data[username][-1]['comment_id'] if comments_data[username] else None
        new_comments = fetch_new_comments(user_id, username, post_id, last_comment_id)
        if new_comments:
            print(f"New comments fetched: {new_comments} (App Version: {app_version})")
        
        # Wait until the next cycle
        current_time = time.time()
        if next_cycle_time and current_time < next_cycle_time:
            time_until_next_cycle = next_cycle_time - current_time
            print(f"Waiting for {int(time_until_next_cycle)} seconds until the next cycle. (App Version: {app_version})")
            time.sleep(time_until_next_cycle)
        
        # Set the next cycle time
        next_cycle_time = current_time + random.randint(1800, 3600)  # Next cycle in 30 to 60 minutes

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
