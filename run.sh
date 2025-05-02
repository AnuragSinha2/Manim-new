#!/bin/bash
# Script to build and run the Manim API Docker container

# Create necessary directories
mkdir -p output uploads temp

# Build the Docker image
echo "Building Docker image..."
docker build -t manim-api .

# Run the container
echo "Running Manim API container..."
docker run -p 8000:8000 \
  -v "$(pwd)/output:/manim/output" \
  -v "$(pwd)/uploads:/manim/uploads" \
  -v "$(pwd)/temp:/manim/temp" \
  manim-api

# Alternatively, you can use docker-compose:
# docker-compose up --build 