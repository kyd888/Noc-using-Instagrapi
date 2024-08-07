document.addEventListener('DOMContentLoaded', function() {
    const loginForm = document.getElementById('login-form');
    const continueSessionSection = document.getElementById('continue-session-section');
    const profileInfo = document.getElementById('profile-info');
    const mainContent = document.getElementById('main-content');
    const monitorForm = document.getElementById('monitor-form');
    const postUrlsList = document.getElementById('post-urls');
    const commentersInterestsList = document.getElementById('commenters-interests');

    // Check if there's a saved session
    fetch('/check_saved_session')
        .then(response => response.json())
        .then(data => {
            if (data.has_saved_session) {
                profileInfo.querySelector('#profile-pic').src = `data:image/png;base64,${data.profile_pic_base64}`;
                profileInfo.querySelector('#profile-username').textContent = data.username;
                continueSessionSection.style.display = 'block';
                loginForm.style.display = 'none';
            }
        });

    // Handle login form submission
    loginForm.addEventListener('submit', function(event) {
        event.preventDefault();
        const formData = new FormData(loginForm);
        fetch('/login', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'Login successful') {
                window.location.reload();
            } else {
                alert(data.status);
            }
        });
    });

    // Handle continue session button
    document.getElementById('continue-session').addEventListener('click', function() {
        fetch('/continue_session', {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'Session restored successfully') {
                continueSessionSection.style.display = 'none';
                mainContent.style.display = 'flex';
            } else {
                alert(data.status);
            }
        });
    });

    // Handle monitor form submission
    monitorForm.addEventListener('submit', function(event) {
        event.preventDefault();
        const formData = new FormData(monitorForm);
        fetch('/start_monitoring', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'Monitoring started') {
                alert('Monitoring started');
                mainContent.style.display = 'flex';
            } else {
                alert(data.status);
            }
        });
    });

    // Function to update post URLs and commenters' interests
    function updateMonitoringData() {
        fetch('/get_post_urls')
            .then(response => response.json())
            .then(data => {
                postUrlsList.innerHTML = '';
                data.post_urls.forEach(post => {
                    const li = document.createElement('li');
                    li.textContent = post.url;
                    postUrlsList.appendChild(li);
                });
            });

        fetch('/get_commenters_interests')
            .then(response => response.json())
            .then(data => {
                commentersInterestsList.innerHTML = '';
                Object.entries(data.commenters_interests).forEach(([username, interests]) => {
                    const li = document.createElement('li');
                    li.textContent = `${username}: ${JSON.stringify(interests)}`;
                    commentersInterestsList.appendChild(li);
                });
            });
    }

    // Periodically update monitoring data
    setInterval(updateMonitoringData, 60000);  // Update every 60 seconds
});

