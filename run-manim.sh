#!/bin/bash

# Make sure directories exist
mkdir -p animations media

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Error: Docker is not running or not installed."
  echo "Please start Docker and try again."
  exit 1
fi

# Help text
if [ "$1" == "--help" ] || [ "$1" == "-h" ] || [ "$#" -eq 0 ]; then
  echo "Manim Docker Runner"
  echo ""
  echo "Usage: ./run-manim.sh [OPTIONS] SCENE_FILE SCENE_CLASS"
  echo ""
  echo "Options:"
  echo "  -p    Preview the output file"
  echo "  -l    Use low quality (faster)"
  echo "  -m    Use medium quality"
  echo "  -h    Use high quality (slower)"
  echo "  -q    Quiet mode"
  echo ""
  echo "Examples:"
  echo "  ./run-manim.sh -pql animations/example.py ExampleScene"
  echo "  ./run-manim.sh -ph animations/example.py MathExample"
  echo ""
  exit 0
fi

# Force rebuild if requested
if [ "$1" == "--rebuild" ]; then
  echo "Rebuilding Docker image..."
  docker compose build --no-cache
  shift
fi

# Build the image if it doesn't exist
if ! docker image inspect manim-docker_manim > /dev/null 2>&1; then
  echo "Building Docker image for the first time..."
  docker compose build
fi

# Run the manim command with all arguments
echo "Running Manim with options: $@"
docker compose run manim "$@"

# Set permissions for generated files (helps with file ownership issues)
if [ -d "media" ]; then
  echo "Setting permissions for media directory..."
  # Using current user instead of sudo to avoid permission issues
  chown -R $USER:$(id -gn) media
fi 