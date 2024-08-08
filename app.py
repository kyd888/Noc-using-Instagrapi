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
from io import StringIO, BytesIO
from botocore.exceptions import NoCredentialsError, ClientError as BotoClientError
from instagrapi.exceptions import ClientError
import openai
import base64
from datetime import datetime
from PIL import Image
from json import JSONDecodeError
from clarifai.client.workflow import Workflow
from ibm_watson import NaturalLanguageUnderstandingV1
from ibm_watson.natural_language_understanding_v1 import Features, EntitiesOptions, KeywordsOptions, CategoriesOptions, SentimentOptions

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

# Read Clarifai API keys from environment variables
clarifai_pat = os.environ.get('CLARIFAI_PAT')  # Personal Access Token
clarifai_workflow_url = os.environ.get('CLARIFAI_WORKFLOW_URL')  # Workflow URL

# Read IBM Watson API key and URL from environment variables
ibm_watson_api_key = os.environ.get('IBM_WATSON_API_KEY')
ibm_watson_url = os.environ.get('IBM_WATSON_URL')

# Initialize Watson NLU client
nlu = NaturalLanguageUnderstandingV1(
    version='2021-08-01',
    iam_apikey=ibm_watson_api_key,
    url=ibm_watson_url
)

@app.route('/')
def index():
    return render_template('index.html', version=app_version, csv_data=csv_data_global, commenters_interests=commenters_interests)

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
        print(f"Stored new comments for post {unique_id}: {new_comments}")

        new_csv_data = [{'username': username, 'post_id': unique_id, 'commenter': c[0], 'comment': c[1], 'time': c[2]} for c in new_comments]
        csv_data_global.extend(new_csv_data)
        write_to_s3(csv_data_global, 'NOC_data3.csv')

        for comment in new_comments:
            commenter_username = comment[0]
            profile_data = fetch_instagram_profile(commenter_username)
            if profile_data:
                profile_picture_url = profile_data['profile_picture_url']
                bio_text = profile_data['biography']
                analysis_result = comprehensive_analysis(profile_picture_url, bio_text)
                commenters_interests[commenter_username] = analysis_result
                print(f"Profile analysis for {commenter_username}: {analysis_result}")

    else:
        print(f"No new comments found for post {unique_id} (App Version: {app_version})")

def analyze_image(image_url):
    # Using the workflow URL and PAT for the image classification workflow
    workflow = Workflow(
        url=clarifai_workflow_url, pat=clarifai_pat
    )
    result = workflow.predict_by_url(image_url, input_type="image")
    return result

def analyze_text(text):
    response = nlu.analyze(
        text=text,
        features=Features(
            entities=EntitiesOptions(),
            keywords=KeywordsOptions(),
            categories=CategoriesOptions(),
            sentiment=SentimentOptions()  # Added sentiment analysis as an example
        )
    ).get_result()
    return response

def comprehensive_analysis(profile_picture_url, bio_text):
    # Analyze profile picture for gender, age, and ethnicity
    image_analysis = analyze_image(profile_picture_url)
    
    # Analyze bio text for interests, language, and other attributes
    text_analysis = analyze_text(bio_text)
    
    # Extract gender, age, and ethnicity from image analysis
    gender = image_analysis.results[0].outputs[0].data['gender'] if 'gender' in image_analysis.results[0].outputs[0].data else 'Unknown'
    age = image_analysis.results[0].outputs[0].data['age'] if 'age' in image_analysis.results[0].outputs[0].data else 'Unknown'
    ethnicity = image_analysis.results[0].outputs[0].data['ethnicity'] if 'ethnicity' in image_analysis.results[0].outputs[0].data else 'Unknown'
    
    # Extract language and other attributes from text analysis
    language = text_analysis.get('language', 'unknown')
    categories = text_analysis['categories']
    keywords = text_analysis['keywords']
    
    return {
        'gender': gender,
        'age': age,
        'ethnicity': ethnicity,
        'language': language,
        'categories': categories,
        'keywords': keywords
    }

def fetch_instagram_profile(username):
    try:
        user_info = client.user_info_by_username(username)
        user_id = user_info.pk

        profile_data = {
            'username': user_info.username,
            'full_name': user_info.full_name,
            'biography': user_info.biography,
            'profile_picture_url': user_info.profile_pic_url,  # Added profile picture URL
            'media_count': user_info.media_count,
            'follower_count': user_info.follower_count,
            'following_count': user_info.following_count,
            'posts': []
        }

        medias = client.user_medias(user_id, 10)  # Fetch latest 10 posts
        for media in medias:
            try:
                media_url = media.thumbnail_url if media.media_type == 1 else media.resources[0].thumbnail_url
            except (IndexError, AttributeError) as e:
                print(f"Error processing media post for {username}: {e}")
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

        # Enhanced analysis
        profile_data['interests'] = extract_interests(user_info.biography, profile_data['posts'])
        profile_data['age_estimate'] = estimate_age(user_info.biography, profile_data['posts'])

        return profile_data
    except JSONDecodeError as e:
        print(f"JSONDecodeError: {e} while fetching data for {username}")
        return None
    except ClientError as e:
        print(f"ClientError: {e} while fetching data for {username}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e} while fetching data for {username}")
        return None

def extract_interests(biography, posts):
    candidate_labels = ["music", "travel", "food", "fitness", "gaming", "lifestyle", "technology", "fashion", "sports", "movies", "books", "art"]
    interests = {label: 0 for label in candidate_labels}

    text_data = [biography] + [post['caption'] for post in posts if post['caption']]
    for text in text_data:
        if not text:
            continue
        try:
            result = nlp(text, candidate_labels)
            for label, score in zip(result['labels'], result['scores']):
                interests[label] += score
        except Exception as e:
            print(f"Error analyzing text: {text} with error: {e}")

    sorted_interests = sorted(interests.items(), key=lambda item: item[1], reverse=True)
    return sorted_interests

def estimate_age(biography, posts):
    # Implement age estimation logic here (e.g., analyzing language style, references to historical events, or profile picture analysis)
    # This is a placeholder function, you can implement a more sophisticated logic or use an external API
    return "Unknown"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # Use the PORT environment variable provided by Render
    app.run(host='0.0.0.0', port=port)
