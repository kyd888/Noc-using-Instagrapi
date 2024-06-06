import os
import time
import random
import uuid
from flask import Flask, render_template, request, jsonify, session
from instagrapi import Client
from threading import Thread

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure key
cl = Client()
monitoring = False
comments_data = {}
post_urls = []
last_refresh_time = None
refresh_messages = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    insta_username = request.form['insta_username']
    insta_password = request.form['insta_password']
    try:
        cl.login(insta_username, insta_password)
        session['logged_in'] = True
        return jsonify({'status': 'Login successful'})
    except Exception as e:
        return jsonify({'status': f'Login failed: {str(e)}'})

@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    if not session.get('logged_in'):
        return jsonify({'status': 'Please login first'}), 403

    global monitoring, post_urls, last_refresh_time, refresh_messages
    target_username = request.form['target_username']
    user_id = search_user(target_username)
    
    monitoring = True
    refresh_messages.clear()
    thread = Thread(target=monitor_new_posts, args=(user_id, target_username))
    thread.start()
    
    return jsonify({'status': 'Monitoring started', 'post_urls': post_urls})

@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    global monitoring
    monitoring = False
    return jsonify({'status': 'Monitoring stopped'})

@app.route('/get_comments', methods=['GET'])
def get_comments_data():
    return jsonify(comments_data)

@app.route('/get_post_urls', methods=['GET'])
def get_post_urls():
    return jsonify({'post_urls': post_urls, 'last_refresh_time': last_refresh_time, 'refresh_messages': refresh_messages})

def search_user(username):
    user_id = cl.user_id_from_username(username)
    print(f"User ID for {username} is {user_id}")
    return user_id

def get_latest_post(user_id):
    posts = cl.user_medias(user_id, amount=1)
    if posts:
        print(f"Latest post ID: {posts[0].pk}")
    else:
        print("No posts found.")
    return posts[0] if posts else None

def get_comments(media_id, limit=20):
    comments = cl.media_comments(media_id, amount=limit)
    comments_list = [(comment.user.username, comment.text, comment.created_at) for comment in comments]
    print(f"Comments for media ID {media_id}: {comments_list}")
    return comments_list

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
            comments_data[unique_id] = get_comments(latest_post.pk)
            last_refresh_time = time.strftime('%Y-%m-%d %H:%M:%S')
        sleep_interval = random.randint(45, 90)  # Randomize interval between 45 to 90 seconds
        print(f"Sleeping for {sleep_interval} seconds.")
        time.sleep(sleep_interval)

        # Refresh comments for each post URL
        for post in post_urls:
            post_code = post['url'].split('/')[-2]
            post_media_id = cl.media_id(post_code)
            new_comments = get_comments(post_media_id)
            comments_data[post['id']] = new_comments
            refresh_message = f"Refreshing comments for post {post['id']} at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            refresh_messages.append(refresh_message)
            print(refresh_message)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
