$(document).ready(function() {
    let monitoring = false;
    let commentsQueue = [];
    let commentIndex = 0;
    let countdownInterval;

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
                    startCountdown();  // Start countdown when monitoring starts
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
                clearInterval(countdownInterval);  // Stop countdown when monitoring stops
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
                    updateCommentsQueue(data.comments);
                });

                $.get('/get_post_urls', function(data) {
                    updateAccountPostsList(data.post_urls);
                });

                checkStatus();
            }, 5000);
        }
    }

    function updateAccountPostsList(data) {
        $('#account-posts-list').empty();
        for (let username in data) {
            if (data.hasOwnProperty(username)) {
                $('#account-posts-list').append(`<h3>Account: ${username}</h3>`);
                const posts = data[username];
                if (Array.isArray(posts)) {
                    posts.forEach(post => {
                        if (post.url && post.id) {
                            $('#account-posts-list').append(`<p><a href="${post.url}" target="_blank">${post.url}</a> (${post.id})</p>`);
                        }
                    });
                }
            }
        }
    }

    function updateCommentsQueue(commentsData) {
        commentsQueue = [];
        for (let username in commentsData) {
            if (commentsData.hasOwnProperty(username)) {
                const posts = commentsData[username];
                if (Array.isArray(posts)) {
                    posts.forEach(post => {
                        if (Array.isArray(post.comments)) {
                            post.comments.forEach(comment => {
                                commentsQueue.push(comment);
                            });
                        }
                    });
                }
            }
        }
        if (commentsQueue.length > 0) {
            displayNextComment();
        }
    }

    function displayNextComment() {
        if (commentsQueue.length > 0) {
            const comment = commentsQueue[commentIndex];
            $('#comment-text').text(`User: ${comment[0]} - Comment: ${comment[1]}`);
            $('#comment-counter').text(`Comment ${commentIndex + 1} of ${commentsQueue.length}`);
            commentIndex = (commentIndex + 1) % commentsQueue.length;
            setTimeout(displayNextComment, 3000); // Cycle through comments every 3 seconds
        } else {
            $('#comment-text').text('');
            $('#comment-counter').text('');
        }
    }

    function startCountdown() {
        clearInterval(countdownInterval);  // Clear any existing intervals
        let interval = Math.floor(Math.random() * (3600 - 1800 + 1)) + 1800;  // Random interval between 30 and 60 minutes
        $('#countdown-timer').text(`${interval} seconds until next monitoring cycle`);

        countdownInterval = setInterval(function() {
            interval--;
            $('#countdown-timer').text(`${interval} seconds until next monitoring cycle`);
            if (interval <= 0) {
                clearInterval(countdownInterval);
                startCountdown();
            }
        }, 1000);
    }
});
