# Use the official Python image from the Docker Hub
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt before the rest of the code to leverage Docker cache
COPY requirements.txt /app/

# Install any necessary dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . /app

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Run app.py when the container launches
CMD ["python", "app.py"]

