#!/bin/bash
set -e

# Set ownership of mounted volumes to the manimuser
# This allows manim to write output files to the host machine
chown -R manimuser:manimgroup /manim/temp /manim/output /manim/media /manim/tts_output /manim/images

# Execute the CMD as manimuser
exec gosu manimuser "$@"
