# app/main.py

import os
import logging
from pathlib import Path
import google.generativeai as genai
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Import routers and services from other modules
from api_routes import router as api_router
from websocket_routes import router as websockets_router
import websocket_routes as ws_module
from tts_service import GeminiTTSService
from image_service import ImageService

# --- Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Manim Animation & TTS API",
    description="Create mathematical animations with synchronized voice-over using Gemini AI.",
    version="3.0.0"
)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Services and Directories ---
try:
    # Load API key from environment
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
    
    # Configure services
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Initialize and assign the TTS service to the websockets module
    tts_service = GeminiTTSService(api_key=GEMINI_API_KEY)
    ws_module.tts_service = tts_service
    
    # Initialize and assign the Image service using Vertex AI
    try:
        GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
        GCP_LOCATION = os.environ["GCP_LOCATION"]
        ws_module.image_service = ImageService(project_id=GCP_PROJECT_ID, location=GCP_LOCATION)
        logger.info("Vertex AI Image Service configured successfully.")
    except KeyError:
        logger.warning("GCP_PROJECT_ID or GCP_LOCATION not set. Image generation will be unavailable.")
        ws_module.image_service = None
    
    logger.info("Gemini API and TTS Service configured successfully.")

except KeyError:
    logger.warning("FATAL: GEMINI_API_KEY environment variable not set. AI and TTS features will be unavailable.")
    ws_module.tts_service = None
    ws_module.image_service = None

# Define and create directories
BASE_DIR = Path("/manim")
DIRECTORIES = [
    BASE_DIR / "animations",
    BASE_DIR / "output",
    BASE_DIR / "temp",
    BASE_DIR / "uploads",
    BASE_DIR / "tts_output",
    BASE_DIR / "images" # Add images directory for the new service
]
for directory in DIRECTORIES:
    directory.mkdir(parents=True, exist_ok=True)

# --- Static Files ---
# Mount the output directory to serve generated videos
app.mount("/output", StaticFiles(directory=str(BASE_DIR / "output")), name="output")
# Mount the generated images directory
app.mount("/images", StaticFiles(directory=str(BASE_DIR / "images")), name="images")
# Mount the frontend static files
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend")), name="static")

# --- Include Routers ---
# Handles WebSocket connections
app.include_router(websockets_router)
# Handles standard HTTP requests (e.g., serving the frontend)
app.include_router(api_router)

# --- Main Entry Point ---
if __name__ == "__main__":
    import uvicorn
    # Note: Uvicorn should be run from the command line for production, e.g., `uvicorn app.main:app --host 0.0.0.0 --port 8000`
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
