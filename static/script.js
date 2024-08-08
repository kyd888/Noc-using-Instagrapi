$(document).ready(function() {
    let monitoring = false;

    checkSavedSession();

    function checkSavedSession() {
        console.log("Checking for saved session...");
        $.get('/check_saved_session', function(response) {
            if (response.has_saved_session) {
                console.log("Saved session found.");
                if (response.profile_pic_base64) {
                    $('#profile-pic').attr('src', 'data:image/jpeg;base64,' + response.profile_pic_base64);
                }
                $('#profile-username').text(response.username);
                $('#login-form').hide();
                $('#continue-session-section').show();
            } else {
                console.log("No saved session found.");
            }
        }).fail(function() {
            console.error("Failed to check for saved session.");
        });
    }

    $('#continue-session').click(function() {
        console.log("Continuing saved session...");
        $.post('/continue_session', function(response) {
            alert(response.status);
            if (response.status === 'Session restored successfully') {
                $('#continue-session-section').hide();
                $('#main-content').show();
                fetchCommentersInterests();
            }
        }).fail(function() {
            console.error("Failed to continue session.");
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
        console.log("Logging in...");
        $.post('/login', $(this).serialize(), function(response) {
            alert(response.status);
            $loginButton.text('Login').prop('disabled', false);
            if (response.status === 'Login successful') {
                $('#login-form').hide();
                $('#main-content').show();
                fetchCommentersInterests();
            }
        }).fail(function() {
            console.error("Failed to login.");
            $loginButton.text('Login').prop('disabled', false);
        });
    });

    $('#monitor-form').submit(function(event) {
        event.preventDefault();
        if (!monitoring) {
            const $startButton = $('#start-monitoring');
            $startButton.text('Loading...').prop('disabled', true);
            const usernames = $('#target_usernames').val().split(',').map(name => name.trim());
            console.log("Starting monitoring for usernames:", usernames);
            $.post('/start_monitoring', { target_usernames: usernames.join(',') }, function(response) {
                alert(response.status);
                if (response.status === 'Monitoring started') {
                    monitoring = true;
                    $startButton.hide();
                    $('#stop-monitoring').show();
                    fetchCommentersInterests();
                } else {
                    $startButton.text('Start Monitoring').prop('disabled', false);
                }
            }).fail(function() {
                console.error("Failed to start monitoring.");
                $startButton.text('Start Monitoring').prop('disabled', false);
            });
        }
    });

    $('#stop-monitoring').click(function() {
        if (monitoring) {
            const $stopButton = $(this);
            $stopButton.text('Loading...').prop('disabled', true);
            console.log("Stopping monitoring...");
            $.post('/stop_monitoring', function(response) {
                alert(response.status);
                monitoring = false;
                $stopButton.text('Stop Monitoring').hide();
                $('#start-monitoring').show().text('Start Monitoring').prop('disabled', false);
            }).fail(function() {
                console.error("Failed to stop monitoring.");
                $stopButton.text('Stop Monitoring').prop('disabled', false);
            });
        }
    });

    function fetchCommentersInterests() {
        if (monitoring) {
            console.log("Fetching commenters' interests...");
            $.get('/get_post_urls', function(data) {
                updateCommentersInterestsList(data.commenters_interests);
                $('#countdown').text(`${data.seconds_until_next_cycle} seconds until next monitoring cycle`);
                if (monitoring) {
                    setTimeout(fetchCommentersInterests, 5000);  // Keep polling every 5 seconds
                }
            }).fail(function() {
                console.error("Failed to fetch commenters' interests.");
                if (monitoring) {
                    setTimeout(fetchCommentersInterests, 5000);  // Retry after 5 seconds
                }
            });
        }
    }

    function updateCommentersInterestsList(data) {
        console.log("Updating commenters' interests list...");
        $('#commenters-interests-list').empty();
        for (let commenter in data) {
            const interests = data[commenter];
            const commenterElement = `<h3>${commenter}</h3><ul>${interests.map(interest => `<li>${interest[0]}: ${interest[1]}</li>`).join('')}</ul>`;
            $('#commenters-interests-list').append(commenterElement);
        }
    }
});

