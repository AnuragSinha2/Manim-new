# Manim Docker Container

This repository contains a Docker configuration for running [Manim](https://www.manim.community/), a mathematical animation engine.

## Setup

1. Make sure you have Docker installed and running on your system.
2. Clone this repository:
   ```
   git clone <repository-url>
   cd manim-docker
   ```
3. Build the Docker image:
   ```
   docker compose build
   ```

## Directory Structure

- `animations/`: Place your Python files with Manim scenes here
- `media/`: Output directory where rendered videos/images will be saved

## Usage

### Running a Scene

Create a Python file in the `animations` directory, for example `animations/example.py`:

```python
from manim import *

class ExampleScene(Scene):
    def construct(self):
        circle = Circle()
        circle.set_fill(BLUE, opacity=0.5)
        circle.set_stroke(BLUE_E, width=4)
        square = Square()

        self.play(Create(square))
        self.wait()
        self.play(Transform(square, circle))
        self.wait()
```

Then run the scene using:

```bash
# Using the helper script (recommended)
./run-manim.sh -pql animations/example.py ExampleScene

# Or directly with Docker
docker compose run manim -pql animations/example.py ExampleScene
```

Command options:
- `-p`: Preview the output file
- `-l`: Use low quality (faster)
- `-m`: Use medium quality
- `-h`: Use high quality (slower)
- `-q`: Quiet mode

The rendered video will be available in the `media` directory.

### Rebuilding the Container

If you need to rebuild the container (e.g., after modifying the Dockerfile):

```bash
./run-manim.sh --rebuild
```

### Interactive Shell

To enter an interactive shell in the container:

```bash
docker compose run --entrypoint bash manim
```

## Troubleshooting

- **Docker not running**: Make sure Docker is installed and the Docker daemon is running
- **Permission issues**: The script automatically sets permissions on the media directory
- **Missing directories**: The script creates `animations` and `media` directories if they don't exist
- **Build issues**: If you encounter problems during the build, try rebuilding with `./run-manim.sh --rebuild`

## Technical Details

This container:
- Uses Ubuntu 22.04 as the base image
- Installs Python, required libraries (Cairo, Pango), and FFmpeg
- Installs a full LaTeX distribution for mathematical formulas
- Installs Manim using pip
- Sets up appropriate volume mappings for your animations and output media

## Customization

You can modify the Dockerfile to install additional packages or change settings as needed.

# Manim API Docker

This Docker container provides a FastAPI web service that allows you to run [Manim](https://www.manim.community/) animations through a REST API.

## Quick Start

1. Build the Docker image:
   ```bash
   docker build -t manim-api .
   ```

2. Run the container:
   ```bash
   docker run -p 8000:8000 -v $(pwd)/output:/manim/output manim-api
   ```

3. Access the API documentation at http://localhost:8000/docs

## API Endpoints

### Run a Manim Command

```http
POST /run-command
```

Request body:
```json
{
  "command": "example.py SquareToCircle",
  "quality": "medium_quality",
  "args": ["--format", "gif"]
}
```

- `command`: The Manim command to run (e.g., file name and scene name)
- `quality`: Quality setting (`low_quality`, `medium_quality`, `high_quality`, `production_quality`)
- `args`: Additional arguments to pass to Manim

### Upload and Run a Python File

```http
POST /run-python-file
```

Form data:
- `file`: The Python file containing Manim scenes
- `quality`: Quality setting (default: `medium_quality`)
- `scene_name`: Optional scene name to render
- `args`: Optional additional arguments as a string

### List Files for a Job

```http
GET /jobs/{job_id}/files
```

### Download a File

```http
GET /jobs/{job_id}/files/{file_name}
```

## Model Context Protocol (MCP) Integration

This API now supports the [Model Context Protocol (MCP)](https://github.com/tadata-org/fastapi_mcp), allowing AI assistants to directly interact with Manim capabilities.

### MCP Endpoint

The MCP endpoint is available at:

```
http://localhost:8000/mcp
```

### Using with AI Assistants

AI assistants like Claude that support MCP can use this API to:

1. Discover available Manim animation capabilities
2. Run Manim commands to generate animations
3. Upload and execute Python files with custom scenes
4. Access generated media files

This integration makes it possible for AI assistants to create mathematical animations through natural language requests.

### MCP Authentication

The MCP integration uses the same authentication as the REST API. If you've configured API keys or other authentication methods, they will be applied to MCP requests as well.

## Examples

### Using curl to run a Manim command:

```bash
curl -X POST http://localhost:8000/run-command \
  -H "Content-Type: application/json" \
  -d '{"command": "temp/example.py SquareToCircle", "quality": "low_quality"}'
```

### Using curl to upload and run a Python file:

```bash
curl -X POST http://localhost:8000/run-python-file \
  -F "file=@example.py" \
  -F "quality=low_quality" \
  -F "scene_name=SquareToCircle"
```

## Volumes

Mount these volumes when running the container:

- `/manim/output`: For accessing generated media files
- `/manim/uploads`: For persistent storage of uploaded files
- `/manim/temp`: For temporary files

Example:
```bash
docker run -p 8000:8000 \
  -v $(pwd)/output:/manim/output \
  -v $(pwd)/uploads:/manim/uploads \
  -v $(pwd)/temp:/manim/temp \
  manim-api
```