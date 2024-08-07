<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Instagram Monitoring</title>
    <style>
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            border: 1px solid black;
            padding: 8px;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
        }
    </style>
</head>
<body>
    <h1>Instagram Monitoring - Version {{ version }}</h1>
    <h2>Commenters and Their Interests</h2>
    <table id="interests-table">
        <thead>
            <tr>
                <th>Username</th>
                <th>Interests</th>
            </tr>
        </thead>
        <tbody id="interests-body">
            {% for username, interests in commenters_interests.items() %}
                <tr>
                    <td>{{ username }}</td>
                    <td>{{ interests }}</td>
                </tr>
            {% endfor %}
        </tbody>
    </table>

    <script>
        function fetchInterests() {
            fetch('/get_commenters_interests')
                .then(response => response.json())
                .then(data => {
                    const interestsBody = document.getElementById('interests-body');
                    interestsBody.innerHTML = ''; // Clear the table body
                    for (const [username, interests] of Object.entries(data.commenters_interests)) {
                        const row = document.createElement('tr');
                        const usernameCell = document.createElement('td');
                        usernameCell.textContent = username;
                        const interestsCell = document.createElement('td');
                        interestsCell.textContent = JSON.stringify(interests);
                        row.appendChild(usernameCell);
                        row.appendChild(interestsCell);
                        interestsBody.appendChild(row);
                    }
                })
                .catch(error => console.error('Error fetching interests:', error));
        }

        setInterval(fetchInterests, 10000); // Fetch data every 10 seconds
        fetchInterests(); // Initial fetch
    </script>
</body>
</html>
