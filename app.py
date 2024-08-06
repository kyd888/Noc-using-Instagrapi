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
from botocore.exceptions import NoCredentialsError, ClientError as BotoClientError
from instagrapi.exceptions import ClientError
import openai
import base64
from transformers import pipeline
from datetime import datetime
from PIL import Image
from io import BytesIO, StringIO
import gc  # Import garbage collection module

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key')  # Replace with a secure key

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
    return render_template('index.html', version=app_version, commenters_interests=commenters_interests)

@app.route('/check_saved_session', methods=['GET'])
def check_saved_session():
    saved_session = session.get('ig_session')
    if saved_session:
        profile_pic_url = session.get('profile_pic_url', '')
        username = session.get('ig_username', '')
        # Fetch the profile picture on the server side
        if profile_pic_url:
            try:
                response = requests.get(profile_pic_url)
                response.raise_for_status()
                profile_pic_data = response.content
                # Encode the image in base64
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
    
    aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
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
        session['ig_session'] = client.get_settings()
        session['ig_username'] = insta_username

        # Fetch and save the profile picture URL
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
    global monitoring, commenters_interests, last_refresh_time, refresh_messages, comments_data
    monitoring[username] = True
    refresh_messages[username] = []
    comments_data[username] = []
    commenters_interests[username] = []
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

    # Ensure next_cycle_time is defined before calculating the time until next cycle
    time_until_next_cycle = max(0, int(next_cycle_time - time.time())) if next_cycle_time else "Unknown"
    
    return jsonify({'commenters_interests': commenters_interests, 'seconds_until_next_cycle': time_until_next_cycle})

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
        except JSONDecodeError as e:
            log_full_response(func)
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
            return posts[0]
        else:
            print("No posts found or user is private. (App Version: {app_version})")
            return None
    except JSONDecodeError as e:
        log_full_response(f"https://www.instagram.com/{user_id}/?__a=1&__d=dis")
        print(f"JSONDecodeError: {e} (App Version: {app_version})")
        return None
    except requests.exceptions.RequestException as e:
        print(f"RequestException: {e} (App Version: {app_version})")
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
    global monitoring, last_refresh_time, refresh_messages, next_cycle_time
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
        return latest_post, post_url, unique_id
    return None, None, None

def handle_new_post(username, post_url, unique_id, media_id):
    global commenters_interests
    new_comments = get_comments(media_id, 10)  # Get 10 new comments
    new_comments = [c for c in new_comments if c[0] != username]
    if new_comments:
        new_csv_data = [{'username': username, 'post_id': unique_id, 'commenter': c[0], 'comment': c[1], 'time': c[2]} for c in new_comments]
        
        # Process each commenter's profile data
        for comment in new_comments:
            commenter_username = comment[0]
            profile_data = fetch_instagram_profile(commenter_username)
            if profile_data:
                if len(profile_data['posts']) < 5:  # Check if the profile has less than 5 posts
                    print(f"Skipping {commenter_username} due to insufficient posts for analysis. (App Version: {app_version})")
                    continue

                captions = [post['caption'] for post in profile_data['posts']]
                images = [post['media_url'] for post in profile_data['posts']]
                print(f"Analyzing interests for commenter: {commenter_username}")
                interests = analyze_interests(captions, images)
                profile_data['interests'] = interests

                # Store username and interests in commenters_interests
                commenters_interests[commenter_username] = interests

                print(f"Interests for {commenter_username}: {json.dumps(interests, indent=4)} (App Version: {app_version})")

        # Offload data to S3 immediately after processing
        write_to_s3(new_csv_data, f'NOC_data_{uuid.uuid4().hex}.csv')
        del new_csv_data  # Clear the data to free up memory
        gc.collect()  # Invoke garbage collection to free up memory

    else:
        print(f"No new comments found for post {unique_id} (App Version: {app_version})")

def analyze_interests(captions, images):
    print("Starting interest analysis...")
    text_classifier = pipeline('zero-shot-classification', model='facebook/bart-large-mnli')
    image_classifier = pipeline('image-classification')

    candidate_labels = ["fitness", "travel", "food", "music", "fashion", "technology", "sports", "movies", "books", "art"]

    interests = {label: 0 for label in candidate_labels}

    print("Analyzing captions...")
    for caption in captions:
        if not caption:
            continue
        print(f"Classifying caption: {caption}")
        result = text_classifier(caption, candidate_labels)
        for label, score in zip(result['labels'], result['scores']):
            interests[label] += score

    print("Analyzing images...")
    for image_url in images:
        try:
            print(f"Fetching image from URL: {image_url}")
            response = requests.get(image_url)
            img = Image.open(BytesIO(response.content))
            result = image_classifier(img)
            for res in result:
                if res['label'] in candidate_labels:
                    interests[res['label']] += res['score']
        except Exception as e:
            print(f"Error analyzing image: {e}")

    sorted_interests = sorted(interests.items(), key=lambda item: item[1], reverse=True)
    print(f"Interests analysis result: {sorted_interests}")
    return sorted_interests

def fetch_instagram_profile(username):
    try:
        user_info = client.user_info_by_username(username)
        user_id = user_info.pk

        profile_data = {
            'username': user_info.username,
            'full_name': user_info.full_name,
            'biography': user_info.biography,
            'media_count': user_info.media_count,
            'follower_count': user_info.follower_count,
            'following_count': user_info.following_count,
            'posts': []
        }

        medias = client.user_medias(user_id, 10)  # Fetch latest 10 posts
        if not medias:
            print(f"No posts found for user {username} or user is private. (App Version: {app_version})")
            return None
        
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

def log_full_response(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        print(f"Full response from {url}: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"RequestException while fetching {url}: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # Use the PORT environment variable provided by Render
    app.run(host='0.0.0.0', port=port)
