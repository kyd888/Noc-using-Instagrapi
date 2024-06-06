import os
import time
from flask import Flask, render_template, request, jsonify, session
from instagrapi import Client
from threading import Thread

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure key
cl = Client()
monitoring = False
comments_data = []

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

    global monitoring
    target_username = request.form['target_username']
    user_id = search_user(target_username)
    
    monitoring = True
    thread = Thread(target=monitor_new_posts, args=(user_id,))
    thread.start()
    
    return jsonify({'status': 'Monitoring started'})

@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    global monitoring
    monitoring = False
    return jsonify({'status': 'Monitoring stopped'})

@app.route('/get_comments', methods=['GET'])
def get_comments_data():
    return jsonify(comments_data)

def search_user(username):
    user_id = cl.user_id_from_username(username)
    return user_id

def get_latest_post(user_id):
    posts = cl.user_medias(user_id, amount=1)
    return posts[0] if posts else None

def get_comments(media_id):
    comments = cl.media_comments(media_id)
    comments_list = [(comment.user.username, comment.text, comment.created_at) for comment in comments]
    return comments_list

def monitor_new_posts(user_id, check_interval=60):
    global comments_data, monitoring
    last_post_id = None
    while monitoring:
        latest_post = get_latest_post(user_id)
        if latest_post and latest_post.pk != last_post_id:
            last_post_id = latest_post.pk
            comments_data = get_comments(latest_post.pk)
        time.sleep(check_interval)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
