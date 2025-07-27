#!/bin/bash
# docker-entrypoint.sh - Enhanced entrypoint with TTS initialization

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🎬 Starting Manim TTS API Service${NC}"

# Check if GEMINI_API_KEY is set
if [ -z "$GEMINI_API_KEY" ]; then
    echo -e "${RED}❌ Error: GEMINI_API_KEY environment variable is not set${NC}"
    echo -e "${YELLOW}Please set your Gemini API key in the .env file or environment variables${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Gemini API key found${NC}"

# Create necessary directories if they don't exist
echo -e "${YELLOW}📁 Creating directories...${NC}"
mkdir -p /manim/animations
mkdir -p /manim/output
mkdir -p /manim/temp
mkdir -p /manim/uploads
mkdir -p /manim/tts_output
mkdir -p /manim/media
mkdir -p /manim/logs

# Set permissions
chmod 755 /manim/animations
chmod 755 /manim/output
chmod 755 /manim/temp
chmod 755 /manim/uploads
chmod 755 /manim/tts_output
chmod 755 /manim/media
chmod 755 /manim/logs

echo -e "${GREEN}✅ Directories created and permissions set${NC}"

# Test Gemini API connection
echo -e "${YELLOW}🔗 Testing Gemini API connection...${NC}"
python3 -c "
import os
import google.generativeai as genai
try:
    genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
    model = genai.GenerativeModel('gemini-2.5-flash-preview')
    print('✅ Gemini API connection successful')
except Exception as e:
    print(f'❌ Gemini API connection failed: {e}')
    exit(1)
" || exit 1

# Test audio libraries
echo -e "${YELLOW}🔊 Testing audio libraries...${NC}"
python3 -c "
try:
    import librosa
    import pygame
    import soundfile
    print('✅ Audio libraries loaded successfully')
except ImportError as e:
    print(f'❌ Audio library import failed: {e}')
    exit(1)
"

# Test Manim installation
echo -e "${YELLOW}🎭 Testing Manim installation...${NC}"
python3 -c "
try:
    import manim
    print(f'✅ Manim version: {manim.__version__}')
except ImportError as e:
    print(f'❌ Manim import failed: {e}')
    exit(1)
"

# Initialize audio system
echo -e "${YELLOW}🎵 Initializing audio system...${NC}"
python3 -c "
try:
    import pygame
    pygame.mixer.pre_init(frequency=22050, size=-16, channels=2, buffer=1024)
    pygame.mixer.init()
    print('✅ Audio system initialized')
except Exception as e:
    print(f'⚠️  Audio system warning: {e}')
"

echo -e "${GREEN}🚀 All systems ready! Starting service...${NC}"

# Execute the main command
exec "$@"