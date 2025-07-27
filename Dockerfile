# Dockerfile - Enhanced with TTS support

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libcairo2-dev \
    libpango1.0-dev \
    pkg-config \
    python3-dev \
    libgirepository1.0-dev \
    libportaudio2 \
    libasound-dev \
    build-essential \
    git \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install LaTeX (minimal)
RUN apt-get update && apt-get install -y \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /manim

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p /manim/animations \
             /manim/output \
             /manim/temp \
             /manim/uploads \
             /manim/tts_output \
             /manim/media \
             /manim/app

# Copy application files
COPY app/ ./app/
COPY frontend/ ./frontend/
COPY animations/ ./animations/
COPY docker-entrypoint.sh /usr/local/bin/

# Make entrypoint executable
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Set environment variables
ENV PYTHONPATH=/manim
ENV MANIMGL_LOG_DIR=/manim/logs

# Expose port for API
EXPOSE 8000

# Default entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]