$(document).ready(function() {
    let monitoring = false;

    // Initialize WebSocket connection
    var socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);

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
                fetchCommentersInterests();
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
                fetchCommentersInterests();
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
                    fetchCommentersInterests();
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

    function fetchCommentersInterests() {
        if (monitoring) {
            setTimeout(function() {
                $.get('/get_post_urls', function(data) {
                    updateCommentersInterestsList(data.commenters_interests);
                    $('#countdown').text(`${data.seconds_until_next_cycle} seconds until next monitoring cycle`);
                });

                fetchCommentersInterests();
            }, 5000);
        }
    }

    function updateCommentersInterestsList(data) {
        $('#commenters-interests-list').empty();
        for (let commenter in data) {
            const interests = data[commenter];
            const commenterElement = `<h3>${commenter}</h3><ul>${interests.map(interest => `<li>${interest[0]}: ${interest[1]}</li>`).join('')}</ul>`;
            $('#commenters-interests-list').append(commenterElement);
        }
    }

    // Listen for new interests via WebSocket
    socket.on('new_interests', function(data) {
        const commenterElement = `<h3>${data.commenter}</h3><ul>${data.interests.map(interest => `<li>${interest[0]}: ${interest[1]}</li>`).join('')}</ul>`;
        $('#commenters-interests-list').append(commenterElement);
    });
});
