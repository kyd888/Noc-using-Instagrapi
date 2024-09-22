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
import base64
from datetime import datetime
from flask_socketio import SocketIO, emit

# Initialize Flask and SocketIO
app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with your secret key
socketio = SocketIO(app)

client = None  # Store the client for the single account
s3 = None  # Store the S3 client
bucket_name = None
monitoring = {}
comments_data = {}
commenters_interests = {}
last_refresh_time = {}
refresh_messages = {}
csv_data_global = []  # Store CSV data to display on the web page
post_urls = {}  # Initialize post URLs
next_cycle_time = time.time()  # Initialize next cycle time

# Mock AWS configuration for testing
aws_access_key = 'mock_access_key'
aws_secret_key = 'mock_secret_key'
aws_region = 'us-east-1'
bucket_name = 'mock-bucket'

# Mock Instagram profile for testing
def mock_fetch_instagram_profile(username):
    print(f"Fetching mock profile for {username}")
    return {
        'username': username,
        'full_name': 'Test User',
        'biography': 'This is a test biography.',
        'media_count': 5,
        'follower_count': 1500,
        'following_count': 300,
        'posts': [
            {
                'id': '123',
                'caption': 'First post!',
                'media_type': 'IMAGE',
                'media_url': 'https://example.com/image1.jpg',
                'timestamp': '2023-09-01',
                'likes': 100,
                'comments': 10
            }
        ]
    }

# Emit a message when the profile analysis starts
def start_profile_analysis(username):
    socketio.emit('analysis_start', {'username': username})
    time.sleep(3)  # Simulate profile analysis delay
    socketio.emit('analysis_complete', {'username': username})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze_profile', methods=['POST'])
def analyze_profile():
    username = request.form['username']
    profile_data = mock_fetch_instagram_profile(username)  # Using mock data for testing
    print(profile_data)
    start_profile_analysis(username)  # Start profile analysis
    return jsonify({'status': f'Analysis started for {username}', 'data': profile_data})

@app.route('/debug_test_profile', methods=['GET'])
def debug_test_profile():
    test_username = 'single_test_user'
    start_profile_analysis(test_username)
    return f"Analysis started for {test_username}. Check logs for results."

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))  # Use the PORT environment variable provided by Render
    socketio.run(app, host='0.0.0.0', port=port)
