$(document).ready(function() {
    let monitoring = false;

    checkSavedSession();

    function checkSavedSession() {
        $.get('/check_saved_session', function(response) {
            if (response.has_saved_session) {
                if (response.profile_pic_base64) {
                    $('#profile-pic').attr('src', 'data:image/jpeg;base64,' + response.profile_pic_base64);
                }
                $('#profile-username').text(response.username);
                $('#login-form').hide();
                $('#continue-session-section').show();
            }
        });
    }

    $('#continue-session').click(function() {
        $.post('/continue_session', function(response) {
            alert(response.status);
            if (response.status === 'Session restored successfully') {
                $('#continue-session-section').hide();
                $('#main-content').show();
            }
        });
    });

    $('#new-login').click(function() {
        $('#continue-session-section').hide();
        $('#login-form').show();
    });

    $('#login-form').submit(function(event) {
        event.preventDefault();
        const $loginButton = $(this).find('button[type="submit"]');
        $loginButton.text('Loading...').prop('disabled', true);
        $.post('/login', $(this).serialize(), function(response) {
            alert(response.status);
            $loginButton.text('Login').prop('disabled', false);
            if (response.status === 'Login successful') {
                $('#login-form').hide();
                $('#main-content').show();
            }
        }).fail(function() {
            $loginButton.text('Login').prop('disabled', false);
        });
    });

    $('#monitor-form').submit(function(event) {
        event.preventDefault();
        if (!monitoring) {
            const $startButton = $('#start-monitoring');
            $startButton.text('Loading...').prop('disabled', true);
            const usernames = $('#target_usernames').val().split(',').map(name => name.trim());
            $.post('/start_monitoring', { target_usernames: usernames.join(',') }, function(response) {
                alert(response.status);
                if (response.status === 'Monitoring started') {
                    monitoring = true;
                    $startButton.hide();
                    $('#stop-monitoring').show();
                    checkStatus();
                } else {
                    $startButton.text('Start Monitoring').prop('disabled', false);
                }
            }).fail(function() {
                $startButton.text('Start Monitoring').prop('disabled', false);
            });
        }
    });

    $('#stop-monitoring').click(function() {
        if (monitoring) {
            const $stopButton = $(this);
            $stopButton.text('Loading...').prop('disabled', true);
            $.post('/stop_monitoring', function(response) {
                alert(response.status);
                monitoring = false;
                $stopButton.text('Stop Monitoring').hide();
                $('#start-monitoring').show().text('Start Monitoring').prop('disabled', false);
            }).fail(function() {
                $stopButton.text('Stop Monitoring').prop('disabled', false);
            });
        }
    });

    function checkStatus() {
        if (monitoring) {
            setTimeout(function() {
                $.get('/get_post_urls', function(data) {
                    updateAccountPostsList(data.post_urls);
                    $('#countdown').text(`${data.seconds_until_next_cycle} seconds until next monitoring cycle`);
                });

                checkStatus();
            }, 5000);
        }
    }

    function updateAccountPostsList(data) {
        $('#account-posts-list').empty();
        for (let username in data) {
            $('#account-posts-list').append(`<h3>Account: ${username}</h3>`);
            const posts = data[username];
            posts.forEach(post => {
                $('#account-posts-list').append(`<p><a href="${post.url}" target="_blank">${post.url}</a> (${post.id})</p>`);
            });
        }
    }

    $('#fetch-profile-form').submit(function(event) {
        event.preventDefault();
        const targetUsername = $('#target_username').val().trim();
        if (targetUsername) {
            $.post('/fetch_profile_data', { target_username: targetUsername }, function(response) {
                if (response.status === 'Profile fetched successfully') {
                    displayProfileData(response.profile_data);
                } else {
                    alert(response.status);
                }
            });
        }
    });

    function displayProfileData(profileData) {
        $('#profile-result').empty().append(`
            <h3>Profile: ${profileData.username}</h3>
            <p>Full Name: ${profileData.full_name}</p>
            <p>Biography: ${profileData.biography}</p>
            <p>Followers: ${profileData.follower_count}</p>
            <p>Following: ${profileData.following_count}</p>
            <h4>Top Interests:</h4>
            <ul id="interests-list">
                ${profileData.interests.slice(0, 3).map(interest => `<li>${interest[0]}: ${interest[1]}</li>`).join('')}
            </ul>
        `);
    }
});
