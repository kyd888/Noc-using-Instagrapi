# Use an official Python runtime as a parent image
FROM python:3.8-slim

# Set the working directory in the container
WORKDIR /app

# Install build dependencies and sentencepiece
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    curl \
    pkg-config \
    libsentencepiece-dev \
    && apt-get clean

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# Ensure the cargo binary path is added to the environment
ENV PATH="/root/.cargo/bin:${PATH}"

# Upgrade pip and setuptools
RUN pip install --upgrade pip setuptools

# Copy the requirements file into the container
COPY requirements.txt /app/requirements.txt

# Install the dependencies
RUN pip install -r requirements.txt

# Copy the rest of the application code into the container
COPY . /app

# Command to run the Flask app
CMD ["python", "app.py"]
