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
app_version = "1.1.4"

client = None  # Store the client for the single account
monitoring = {}
comments_data = {}
post_urls = {}
last_refresh_time = {}
refresh_messages = {}
max_cycles = 100  # Set a maximum number of monitoring cycles

# AWS S3 configuration
s3 = boto3.client('s3', 
    aws_access_key_id='YOUR_AWS_ACCESS_KEY', 
    aws_secret_access_key='YOUR_AWS_SECRET_KEY', 
    region_name='us-east-1'  # Replace with your actual region
)
bucket_name = 'your-s3-bucket-name'
csv_filename = 'instagram_data.csv'

@app.route('/')
def index():
    return render_template('index.html', version=app_version)

@app.route('/login', methods=['POST'])
def login():
    global client
    insta_username = request.form['insta_username']
    insta_password = request.form['insta_password']
    try:
        print(f"Attempting to login with username: {insta_username} (App Version: {app_version})")
        client = Client()
        client.login(insta_username, insta_password)
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
    target_usernames = request.form.getlist('target_usernames')  # List of usernames
    for username in target_usernames:
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

@app.ro
