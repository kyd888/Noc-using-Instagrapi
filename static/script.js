$(document).ready(function() {
    let monitoring = false;

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
                $.get('/get_comments', function(data) {
                    $('#accounts_data').empty();
                    for (let username in data.comments) {
                        $('#accounts_data').append(`<h3>Account: ${username}</h3>`);
                        const posts = data.comments[username];
                        posts.forEach(post => {
                            $('#accounts_data').append(`<h4>Post ${post.id}</h4>`);
                            post.comments.forEach(comment => {
                                $('#accounts_data').append(`<p>User: ${comment[0]}<br>Comment: ${comment[1]}<br>Time: ${comment[2]}</p><hr>`);
                            });
                        });
                    }
                });

                $.get('/get_post_urls', function(data) {
                    $('#accounts_data').empty();  // Clear previous data
                    for (let username in data.post_urls) {
                        $('#accounts_data').append(`<h3>Account: ${username}</h3>`);
                        const urls = data.post_urls[username];
                        urls.forEach(post => {
                            $('#accounts_data').append(`<p><a href="${post.url}" target="_blank">${post.url}</a> (${post.id})</p>`);
                        });
                    }
                    for (let username in data.last_refresh_time) {
                        $('#accounts_data').append(`<h4>Last refresh time for ${username}: ${data.last_refresh_time[username]}</h4>`);
                    }
                    for (let username in data.refresh_messages) {
                        $('#accounts_data').append(`<h4>Refresh message for ${username}: ${data.refresh_messages[username]}</h4>`);
                    }
                });

                checkStatus();
            }, 5000);
        }
    }
});
