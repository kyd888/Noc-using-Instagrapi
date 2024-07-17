$(document).ready(function() {
    let monitoring = false;

    $('#login-form').submit(function(event) {
        event.preventDefault();
        $.post('/login', $(this).serialize(), function(response) {
            alert(response.status);
            if (response.status === 'Login successful') {
                $('#login-form').hide();
                $('#main-content').show();
            }
        });
    });

    $('#monitor-form').submit(function(event) {
        event.preventDefault();
        if (!monitoring) {
            const usernames = $('#target_usernames').val().split(',').map(name => name.trim());
            $.post('/start_monitoring', { target_usernames: usernames.join(',') }, function(response) {
                alert(response.status);
                if (response.status === 'Monitoring started') {
                    monitoring = true;
                    $('#start-monitoring').hide();
                    $('#stop-monitoring').show();
                    checkStatus();
                }
            });
        }
    });

    $('#stop-monitoring').click(function() {
        if (monitoring) {
            $.post('/stop_monitoring', function(response) {
                alert(response.status);
                monitoring = false;
                $('#stop-monitoring').hide();
                $('#start-monitoring').show();
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
