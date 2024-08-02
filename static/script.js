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
                fetchCommenterInterests(post.url);
            });
        }
    }

    function fetchCommenterInterests(postUrl) {
        $.get(postUrl, function(postData) {
            const comments = postData.comments;
            comments.forEach(comment => {
                $.post('/get_commenter_interests', { commenter: comment.username }, function(response) {
                    const interests = response.interests;
                    $('#account-posts-list').append(`<p>Commenter: ${comment.username}, Interests: ${interests.map(i => i[0]).join(', ')}</p>`);
                });
            });
        });
    }
});
