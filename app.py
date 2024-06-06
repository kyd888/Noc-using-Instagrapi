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

