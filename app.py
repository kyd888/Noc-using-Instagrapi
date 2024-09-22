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
import base64
from datetime import datetime
from flask_socketio import SocketIO, emit
import json

# Initialize Flask and SocketIO
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key')  # Replace with your secret key
socketio = SocketIO(app)

# Version number
app_version = "1.1.6"

client = None  # Store the client for the single account
s3 = None  # Store the S3 client
bucket_name = None
monitoring = {}
comments_data = {}
commenters_interests = {}  # Store commenters' interests here
last_refresh_time = {}
refresh_messages = {}
csv_data_global = []  # Store the CSV data to display on the web page
post_urls = {}  # Initialize post_urls
max_cycles = 100  # Set a maximum number of monitoring cycles
max_interactions = 50  # Set a maximum number of interactions per session
break_after_actions = 20  # Take a break after this many actions
long_break_probability = 0.1  # Probability of taking a longer break
long_break_duration = 7200  # Longer break duration in seconds (2 hours)
next_cycle_time = time.time()  # Initialize next_cycle_time

# Initialize OpenAI client
openai.api_key = os.environ.get('OPENAI_API_KEY')  # Ensure you have set your OpenAI API key

# Helper function to add random delays between actions
def add_delay(min_seconds=10, max_seconds=30):
    delay = random.uniform(min_seconds, max_seconds)
    print(f"Adding a delay of {delay:.2f} seconds to avoid being flagged.")
    time.sleep(delay)

# Avoid frequent logins
@app.route('/')
def index():
    return render_template('index.html', version=app_version, csv_data=csv_data_global, commenters_interests=commenters_interests)
    
# Emit a message when the profile analysis starts
def start_profile_analysis(username):
    socketio.emit('analysis_start', {'username': username})  # Notify the client that analysis has started
    time.sleep(3)  # Simulate profile analysis delay (replace with actual analysis logic)
    socketio.emit('analysis_complete', {'username': username})  # Notify the client that analysis is complete

@app.route('/check_saved_session', methods=['GET'])
def check_saved_session():
    saved_session = session.get('ig_session')
    if saved_session:
        profile_pic_url = session.get('profile_pic_url', '')
        username = session.get('ig_username', '')
        if profile_pic_url:
            try:
                response = requests.get(profile_pic_url)
                response.raise_for_status()
                profile_pic_data = response.content
                profile_pic_base64 = base64.b64encode(profile_pic_data).decode('utf-8')
                return jsonify({
                    'has_saved_session': True,
                    'profile_pic_base64': profile_pic_base64,
                    'username': username
                })
            except requests.RequestException as e:
                print(f"Error fetching profile picture: {e}")
                return jsonify({'has_saved_session': False})
    return jsonify({'has_saved_session': False})
    
@app.route('/continue_session', methods=['POST'])
def continue_session():
    global client, s3, bucket_name
    saved_session = session.get('ig_session')
    if not saved_session:
        return jsonify({'status': 'No saved session available'}), 403
    try:
        client = Client()
        client.set_settings(saved_session)
        client.login_by_sessionid(client.sessionid)
        session['logged_in'] = True
        return jsonify({'status': 'Session restored successfully'})
    except Exception as e:
        return jsonify({'status': f'Session restore failed: {str(e)}'}), 500

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

        login_with_retries(client, insta_username, insta_password)
        session['logged_in'] = True
        session['ig_session'] = client.get_settings()
        session['ig_username'] = insta_username

        profile_info = client.user_info_by_username(insta_username)
        session['profile_pic_url'] = profile_info.profile_pic_url

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
        
def login_with_retries(client, username, password, retries=5, initial_delay=10):
    delay = initial_delay
    for i in range(retries):
        try:
            client.login(username, password)
            return
        except ClientError as e:
            if 'challenge_required' in str(e):
                print(f"Challenge required for {username}. Handling challenge...")
                handle_challenge(client)
            elif 'Please wait a few minutes before you try again' in str(e):
                print(f"Rate limit hit during login. Retrying in {delay} seconds. (App Version: {app_version})")
                time.sleep(delay + random.uniform(0, delay / 2))  # Add jitter to delay
                delay *= 2  # Exponential backoff
            else:
                raise e
    raise Exception("Maximum retries reached for login")

def handle_challenge(client):
    """Handle Instagram's challenge process (e.g., email or SMS)."""
    try:
        challenge_info = client.challenge_resolve()
        # Handle the challenge choice (e.g., email, SMS)
        if challenge_info.get("step_name") == "select_verify_method":
            choice = challenge_info['step_data']['choice']  # "1" for email, "0" for SMS
            client.challenge_send_verification_code(choice)
            print(f"Enter code (6 digits) for {client.username} (ChallengeChoice.{choice}):")
            code = input("Enter the received code: ").strip()  # Replace this with automatic code retrieval logic if possible
            client.challenge_verify_code(code)
        elif challenge_info.get("step_name") == "verify_code":
            code = input(f"Enter the received code for {client.username}: ").strip()
            client.challenge_verify_code(code)
    except Exception as e:
        print(f"Error handling challenge: {e}")

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

@app.route('/get_post_urls', methods=['GET'])
def get_post_urls():
    if not session.get('logged_in'):
        return jsonify({'error': 'Not logged in'}), 403
    
    return jsonify({'post_urls': post_urls, 'seconds_until_next_cycle': int(next_cycle_time - time.time())})

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
    except Exception as e:
        print(f"Error fetching latest post for user ID {user_id}: {e} (App Version: {app_version})")
        return None

def get_comments(media_id, count=10):
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

def post_monitoring_loop(user_id, username):
    global monitoring, last_refresh_time, refresh_messages, csv_data_global, next_cycle_time, commenters_interests
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

                # Add a random delay after processing a post
                add_delay(30, 60)  # 30 to 60 seconds delay

            sleep_interval = random.randint(1800, 3600)  # Increase sleep interval to 30-60 minutes
            next_cycle_time = time.time() + sleep_interval
            print(f"Sleeping for {sleep_interval} seconds. (App Version: {app_version})")
            time.sleep(sleep_interval)
            cycle_count += 1

            if interaction_count >= 10:  # Break after 10 actions
                print(f"Taking a longer break for 5 minutes after {interaction_count} interactions.")
                time.sleep(300)  # 5-minute break
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
        
        new_csv_data = [{'username': username, 'post_id': unique_id, 'commenter': c[0], 'comment': c[1], 'time': c[2]} for c in new_comments]
        csv_data_global.extend(new_csv_data)
        write_to_s3(csv_data_global, 'NOC_data3.csv')
        print(f"CSV Data: {new_csv_data} (App Version: {app_version})")

        for comment in new_comments:
            commenter_username = comment[0]
            profile_data = fetch_instagram_profile(commenter_username)
            
            if profile_data and len(profile_data['posts']) >= 2:
                captions = [post['caption'] for post in profile_data['posts'][:2] if 'caption' in post]  # Add validation
                images = [post['media_url'] for post in profile_data['posts'][:2] if 'media_url' in post]  # Add validation
                
                interests = analyze_interests(captions, images)
                profile_data['interests'] = interests

                commenters_interests[commenter_username] = interests
                print(f"Interests for {commenter_username}: {json.dumps(interests, indent=4)} (App Version: {app_version})")
                
            else:
                print(f"Skipping {commenter_username} due to insufficient posts or private account (App Version: {app_version})")
    else:
        print(f"No new comments found for post {unique_id} (App Version: {app_version})")
@app.route('/analyze_profile', methods=['POST'])
def analyze_profile():
    username = request.form['username']
    # Start profile analysis in the background
    thread = Thread(target=start_profile_analysis, args=(username,))
    thread.start()
    return jsonify({'status': f'Analysis started for {username}'})
    
def analyze_interests(captions, images):
    candidate_labels = ["fitness", "travel", "food", "music", "fashion", "technology", "sports", "movies", "books", "art"]
    interests = {label: 0 for label in candidate_labels}

    print(f"Analyzing text interests (App Version: {app_version})")
    for caption in captions:
        if not caption:
            continue
        try:
            response = requests.post(
                "https://api-inference.huggingface.co/models/facebook/bart-large-mnli",
                headers={"Authorization": f"Bearer {os.environ['HUGGINGFACE_API_KEY']}"},
                json={"inputs": caption, "parameters": {"candidate_labels": candidate_labels}}
            )
            result = response.json()
            if 'labels' in result and 'scores' in result:
                for label, score in zip(result['labels'], result['scores']):
                    interests[label] += score
            else:
                print(f"Error: Unexpected response format for caption analysis (App Version: {app_version})")
        except Exception as e:
            print(f"Error analyzing caption: {caption} with error: {e}")

    print(f"Analyzing image interests (App Version: {app_version})")
    for image_url in images:
        if not image_url:
            continue
        try:
            response = requests.post(
                "https://api-inference.huggingface.co/models/google/vit-base-patch16-224",
                headers={"Authorization": f"Bearer {os.environ['HUGGINGFACE_API_KEY']}"},
                json={"inputs": image_url}
            )
            result = response.json()
            if isinstance(result, list):
                for res in result:
                    if res.get('label') in candidate_labels:
                        interests[res['label']] += res.get('score', 0)
            else:
                print(f"Error: Unexpected response format for image analysis (App Version: {app_version})")
        except Exception as e:
            print(f"Error analyzing image: {image_url} with error: {e}")

    sorted_interests = sorted(interests.items(), key=lambda item: item[1], reverse=True)
    return sorted_interests
    
def fetch_instagram_profile(username):
    try:
        # Make the request to fetch the user's data
        response = requests.get(f"https://www.instagram.com/{username}/?__a=1&__d=dis")
        
        # Check if the response is valid and is in JSON format
        if response.status_code == 200:
            try:
                profile_data = response.json()  # Attempt to parse the response as JSON
                user_info = profile_data.get("graphql", {}).get("user", {})
                user_id = user_info.get("id", None)
                
                if user_id:
                    print(f"User ID for {username} is {user_id}")
                    return extract_profile_data(user_info)  # Extract and return profile data
                else:
                    print(f"No valid user ID found for {username}. Profile might be private or restricted.")
                    return None
            except json.JSONDecodeError:
                print(f"JSONDecodeError: Failed to parse JSON for {username}")
                return None
        else:
            print(f"Received non-200 status code: {response.status_code} for {username}")
            return None

    except requests.RequestException as e:
        print(f"RequestException: An error occurred while fetching data for {username}: {e}")
        return None

def extract_profile_data(user_info):
    """Extracts and formats the profile data from the user_info dictionary."""
    profile_data = {
        'username': user_info.get('username', ''),
        'full_name': user_info.get('full_name', ''),
        'biography': user_info.get('biography', ''),
        'media_count': user_info.get('edge_owner_to_timeline_media', {}).get('count', 0),
        'follower_count': user_info.get('edge_followed_by', {}).get('count', 0),
        'following_count': user_info.get('edge_follow', {}).get('count', 0),
        'posts': []
    }

    # Extract posts if available
    edges = user_info.get('edge_owner_to_timeline_media', {}).get('edges', [])
    for edge in edges[:10]:  # Limit to the latest 10 posts
        node = edge.get('node', {})
        media_url = node.get('display_url', None)
        caption = node.get('edge_media_to_caption', {}).get('edges', [{}])[0].get('node', {}).get('text', '')
        
        post = {
            'id': node.get('id', ''),
            'caption': caption,
            'media_type': node.get('typename', ''),
            'media_url': media_url,
            'timestamp': node.get('taken_at_timestamp', ''),
            'likes': node.get('edge_liked_by', {}).get('count', 0),
            'comments': node.get('edge_media_to_comment', {}).get('count', 0)
        }
        profile_data['posts'].append(post)

    return profile_data

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))  # Use the PORT environment variable
    socketio.run(app, host='0.0.0.0', port=port)
