# Dockerfile for Manim CE - Optimized for Security and Efficiency

# Use a stable, recent Python base image
FROM python:3.12-slim as base

# Set environment variables to prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# --- System Dependencies ---
# Install all necessary system packages in a single layer
# This includes gosu for user switching, ffmpeg, graphics libraries, and a minimal TeX Live
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    # User switching tool
    gosu \
    # C compiler and build tools
    build-essential \
    # Video/Audio processing
    ffmpeg \
    libportaudio2 \
    portaudio19-dev \
    libasound-dev \
    # Manim's core graphics and text rendering dependencies
    libcairo2-dev \
    libpango1.0-dev \
    # LaTeX for mathematical text
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    dvisvgm \
    # Git for version control
    git \
    # Cleanup
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# --- Application Stage ---
FROM base as final

# Create a non-root user to run the application for security
# Using a static UID/GID is good practice for consistency
ARG UID=1001
ARG GID=1001
RUN groupadd -g $GID manimgroup && \
    useradd -u $UID -g manimgroup -m -s /bin/bash manimuser

# Set the working directory
WORKDIR /manim

# Copy application requirements first to leverage Docker cache
COPY --chown=manimuser:manimgroup requirements.txt .

# Install Python dependencies as the non-root user
# Using --no-cache-dir keeps the image size down
RUN pip install --no-cache-dir -r requirements.txt

# Add the user's local bin directory to the PATH
ENV PATH="/home/manimuser/.local/bin:${PATH}"

# Create and set permissions for all necessary directories
RUN mkdir -p animations media temp uploads tts_output output logs && \
    chown -R manimuser:manimgroup animations media temp uploads tts_output output logs

# Copy the rest of the application code
COPY --chown=manimuser:manimgroup . .

# Switch to the non-root user
USER manimuser

# Expose the port the application will run on
EXPOSE 8000

# Set the entrypoint script
ENTRYPOINT ["/manim/docker-entrypoint.sh"]

# Set the default command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
