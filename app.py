import os
import time
import random
import uuid
from flask import Flask, render_template, request, jsonify, session
from instagrapi import Client
from threading import Thread
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key')  # Replace with a secure key

# Version number
app_version = "1.0.4"

cl = Client()
monitoring = False
comments_data = {}
post_urls = []
last_refresh_time = None
refresh_messages = []

@app.route('/')
def index():
    return render_template('index.html', version=app_version)

@app.route('/login', methods=['POST'])
def login():
    insta_username = request.form['insta_username']
    insta_password = request.form['insta_password']
    try:
        print(f"Attempting to login with username: {insta_username} (App Version: {app_version})")
        cl.login(insta_username, insta_password)
        session['logged_in'] = True
        return jsonify({'status': 'Login successful', 'version': app_version})
    except Exception as e:
        print(f"Login failed: {e} (App Version: {app_version})")
        return jsonify({'status': f'Login failed: {str(e)}', 'version': app_version})

@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    if not session.get('logged_in'):
        return jsonify({'status': 'Please login first', 'version': app_version}), 403

    global monitoring, post_urls, last_refresh_time, refresh_messages, comments_data
    target_username = request.form['target_username']
    user_id = search_user(target_username)
    if user_id is None:
        return jsonify({'status': 'User not found or error occurred', 'version': app_version}), 404

    monitoring = True
    refresh_messages.clear()
    comments_data.clear()
    post_urls.clear()
    thread = Thread(target=monitor_new_posts, args=(user_id, target_username))
    thread.start()
    
    return jsonify({'status': 'Monitoring started', 'post_urls': post_urls, 'version': app_version})

@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    global monitoring
    monitoring = False
    return jsonify({'status': 'Monitoring stopped', 'version': app_version})

@app.route('/get_comments', methods=['GET'])
def get_comments_data():
    print(f"Returning comments data: {comments_data} (App Version: {app_version})")
    return jsonify({'comments': comments_data, 'version': app_version})

@app.route('/get_post_urls', methods=['GET'])
def get_post_urls():
    return jsonify({'post_urls': post_urls, 'last_refresh_time': last_refresh_time, 'refresh_messages': refresh_messages, 'version': app_version})

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
    return retry_with_exponential_backoff(lambda: cl.user_id_from_username(username))

def search_user(username):
    try:
        user_id = get_user_id_with_retry(username)
        print(f"User ID for {username} is {user_id} (App Version: {app_version})")
        return user_id
    except Exception as e:
        print(f"Error fetching user ID for {username}: {e} (App Version: {app_version})")
        return None

def get_latest_post(user_id):
    posts = cl.user_medias(user_id, amount=1)
    if posts:
        print(f"Latest post ID: {posts[0].pk} (App Version: {app_version})")
    else:
        print("No posts found. (App Version: {app_version})")
    return posts[0] if posts else None

def get_one_comment(media_id):
    try:
        comments = cl.media_comments(media_id, amount=1)
        if comments:
            comment = comments[0]
            comment_data = (comment.user.username, comment.text, comment.created_at.strftime('%Y-%m-%d %H:%M:%S'))
            print(f"Fetched one comment for media ID {media_id}: {comment_data} (App Version: {app_version})")
            return comment_data
        else:
            print(f"No comments found for media ID {media_id} (App Version: {app_version})")
            return None
    except Exception as e:
        print(f"Error fetching comments for media ID {media_id}: {e} (App Version: {app_version})")
        return None

def monitor_new_posts(user_id, username):
    global comments_data, monitoring, post_urls, last_refresh_time, refresh_messages
    last_post_id = None
    while monitoring:
        latest_post = get_latest_post(user_id)
        if latest_post and latest_post.pk != last_post_id:
            last_post_id = latest_post.pk
            post_url = f"https://www.instagram.com/p/{latest_post.code}/"
            unique_id = str(uuid.uuid4().int)[:4]
            post_urls.append({'url': post_url, 'id': unique_id})
            comment = get_one_comment(latest_post.pk)
            if comment:
                comments_data[unique_id] = [comment]
                print(f"Stored comment for post {unique_id}: {comment} (App Version: {app_version})")
            else:
                print(f"No comment found for post {unique_id} (App Version: {app_version})")
            last_refresh_time = time.strftime('%Y-%m-%d %H:%M:%S')
        sleep_interval = random.randint(45, 90)  # Randomize interval between 45 to 90 seconds
        print(f"Sleeping for {sleep_interval} seconds. (App Version: {app_version})")
        time.sleep(sleep_interval)

        for post in post_urls:
            post_code = post['url'].split('/')[-2]
            try:
                post_media_id = cl.media_pk_from_code(post_code)
                new_comment = get_one_comment(post_media_id)
                if new_comment:
                    comments_data[post['id']] = [new_comment]
                    refresh_message = f"Refreshing comment for post {post['id']} at {time.strftime('%Y-%m-%d %H:%M:%S')} (App Version: {app_version})"
                    refresh_messages.append(refresh_message)
                    print(refresh_message)
                else:
                    print(f"No new comment found for post {post['id']} (App Version: {app_version})")
            except Exception as e:
                print(f"Error fetching media ID for post code {post_code}: {e} (App Version: {app_version})")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
