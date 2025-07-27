# app/main.py
import os
import asyncio
import logging
import shutil
import json
import re
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import google.generativeai as genai
from .tts_service import GeminiTTSService, TTSRequest, AnimationVoiceSync

# --- Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Manim AI Explainer")

# --- Services and Directories ---
try:
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
    tts_service = GeminiTTSService(GEMINI_API_KEY)
    # Configure the generative model for script creation
    genai.configure(api_key=GEMINI_API_KEY)
    script_model = genai.GenerativeModel('gemini-1.5-flash')
except KeyError:
    logger.warning("GEMINI_API_KEY not set. AI features will be unavailable.")
    tts_service = None
    script_model = None

BASE_DIR = Path("/manim")
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
FRONTEND_DIR = BASE_DIR / "frontend"
TTS_OUTPUT_DIR = BASE_DIR / "tts_output"

for directory in [OUTPUT_DIR, TEMP_DIR, FRONTEND_DIR, TTS_OUTPUT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections = set()
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    async def send_json(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.warning(f"Could not send to websocket: {e}")

manager = ConnectionManager()

# --- Helper Functions ---
async def send_progress(websocket: WebSocket, stage: str, message: str, status: str = "progress"):
    await manager.send_json(websocket, {"status": status, "stage": stage, "message": message})

async def generate_ai_script_and_narration(topic: str, websocket: WebSocket):
    """Generate a robust Manim script and narration using an AI model, with improved error handling."""
    await send_progress(websocket, "AI Scripting", "AI is generating a detailed, reliable script for a 2-minute video...")
    
    if not script_model:
        raise Exception("Generative AI script model is not configured.")

    scene_name = topic.replace(" ", "").capitalize()
    
    prompt = f"""
    You are an expert Manim scriptwriter. Your sole task is to generate a single, raw JSON object without any formatting, markdown, or explanatory text.
    The JSON object must explain the topic: "{topic}".

    The JSON object must contain two keys: "script" and "narration".

    1.  **"script" key**:
        - The value must be a Python script for a Manim `Scene`.
        - The scene class must be named `{scene_name}`.
        - **IMPORTANT**: Use only fundamental Manim objects (e.g., `Circle`, `Square`, `Text`, `Line`) and basic animations (e.g., `Create`, `Write`, `Transform`, `FadeIn`, `FadeOut`). Do NOT use complex community modules, external libraries (other than manim), or obscure features.
        - The script must be self-contained and runnable in a standard Manim environment.
        - The total animation duration, including all `self.wait()` calls, must be approximately 120 seconds.
        - Include simple comments in the script.

    2.  **"narration" key**:
        - The value must be a detailed narration script, synchronized with the animation.
        - The total speaking time should be around 1 minute and 45 seconds.

    **Example JSON Output:**
    {{
      "script": "from manim import *\n\nclass PythagoreanTheorem(Scene):\n    def construct(self):\n        title = Text(\"The Pythagorean Theorem\", font_size=48)\n        self.play(Write(title))\n        self.wait(3)\n        self.play(FadeOut(title))\n\n        triangle = Polygon([-2, -1, 0], [2, -1, 0], [-2, 2, 0], color=BLUE).scale(1.5)\n        a_label = Text(\"a\").next_to(triangle.get_edge_center(DOWN), DOWN)\n        b_label = Text(\"b\").next_to(triangle.get_edge_center(LEFT), LEFT)\n        c_label = Text(\"c\").next_to(triangle.get_edge_center(UP), UP+RIGHT)\n        self.play(Create(triangle), Write(a_label), Write(b_label), Write(c_label))\n        self.wait(10)\n\n        formula = MathTex(\"a^2 + b^2 = c^2\", font_size=72).to_edge(DOWN)\n        self.play(Write(formula))\n        self.wait(10)",
      "narration": "Hello, and welcome. In this video, we will explore the famous Pythagorean Theorem.\n\nLet's begin with a right-angled triangle. We'll label the sides 'a', 'b', and 'c'. The longest side, 'c', is called the hypotenuse.\n\nThe theorem states that the square of side 'a' plus the square of side 'b' is equal to the square of the hypotenuse, 'c'. This fundamental rule of geometry has applications across science and engineering."
    }}
    """
    
    response = await script_model.generate_content_async(prompt)
    
    raw_response_text = response.text
    logger.info(f"Raw AI response: {raw_response_text}")

    # Use regex to find the JSON block, making this more robust
    json_match = re.search(r'\{.*\}', raw_response_text, re.DOTALL)
    if not json_match:
        raise Exception("Could not find a valid JSON object in the AI's response.")
    
    cleaned_response_text = json_match.group(0)
    
    try:
        content = json.loads(cleaned_response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON after cleaning: {cleaned_response_text}")
        raise Exception(f"Failed to decode the AI's JSON response for the script. Error: {e}")

    await send_progress(websocket, "AI Scripting", "AI content generated successfully.")
    return content

async def run_manim_websockets(websocket: WebSocket, script_path: str, scene_name: str, quality: str) -> str:
    await send_progress(websocket, "Manim", f"Starting Manim rendering ({quality})...")
    quality_flags = {"low_quality": "-ql", "medium_quality": "-qm", "high_quality": "-qh", "production_quality": "-qk"}
    
    manim_output_dir = OUTPUT_DIR / "videos" / Path(script_path).stem
    if manim_output_dir.exists():
        shutil.rmtree(manim_output_dir)

    cmd = ["manim", quality_flags.get(quality, "-ql"), "--media_dir", str(OUTPUT_DIR), script_path, scene_name]
    
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    async def stream_logs(stream, log_prefix):
        while True:
            line = await stream.readline()
            if not line: break
            message = line.decode().strip()
            logger.info(f"{log_prefix}: {message}")
            await send_progress(websocket, f"Manim {log_prefix}", message)
    
    await asyncio.gather(stream_logs(process.stdout, "stdout"), stream_logs(process.stderr, "stderr"))
    await process.wait()

    if process.returncode != 0:
        raise Exception(f"Manim rendering failed with exit code {process.returncode}")

    resolution_map = {"low_quality": "480p15", "medium_quality": "720p30", "high_quality": "1080p60", "production_quality": "2160p60"}
    res_folder = resolution_map.get(quality)
    
    expected_dir = OUTPUT_DIR / "videos" / Path(script_path).stem / res_folder
    try:
        output_file = next(expected_dir.glob(f"{scene_name}.mp4"))
        return str(output_file)
    except StopIteration:
        raise FileNotFoundError(f"Could not find the Manim output file in {expected_dir}")

async def combine_audio_video(video_path: str, audio_path: str, output_path: Path) -> str:
    cmd = ["ffmpeg", "-i", video_path, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-shortest", "-y", str(output_path)]
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise Exception(f"FFmpeg failed: {stderr.decode()}")
    return str(output_path)

# --- Main WebSocket Endpoint ---
@app.websocket("/ws/generate-full-animation")
async def ws_generate_full_animation(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        data = await websocket.receive_json()
        topic = data.get("topic", "Default Topic")
        quality = data.get("quality", "low_quality")
        voice = data.get("voice", "Puck")
        scene_name = topic.replace(" ", "").capitalize()

        ai_content = await generate_ai_script_and_narration(topic, websocket)
        script_content, narration_text = ai_content["script"], ai_content["narration"]
        await manager.send_json(websocket, {"script": script_content, "narration": narration_text})
        script_path = TEMP_DIR / f"{scene_name}_script.py"
        script_path.write_text(script_content)

        if not tts_service: raise Exception("TTS Service is not configured.")
        await send_progress(websocket, "TTS", f"Generating voice-over with '{voice}' voice...")
        tts_request = TTSRequest(text=narration_text, voice=voice)
        tts_response = await tts_service.generate_speech(tts_request)
        
        tts_audio_url = f"/tts_output/{Path(tts_response.audio_path).name}"
        await manager.send_json(websocket, {"tts_audio_url": tts_audio_url})

        await send_progress(websocket, "Syncing", "Adjusting animation timing to match voice-over...")
        synced_script_content = AnimationVoiceSync.generate_synced_manim_script(script_content, tts_response)
        synced_script_path = TEMP_DIR / f"{scene_name}_synced_script.py"
        synced_script_path.write_text(synced_script_content)
        await send_progress(websocket, "Syncing", "Synchronization complete.")

        video_path_no_audio = await run_manim_websockets(websocket, str(synced_script_path), scene_name, quality)

        await send_progress(websocket, "FFmpeg", "Combining final video and audio...")
        final_video_path = await combine_audio_video(
            video_path_no_audio, tts_response.audio_path, OUTPUT_DIR / f"{scene_name}_final.mp4"
        )
        
        await manager.send_json(websocket, {
            "status": "completed",
            "output_file": f"/output/{Path(final_video_path).name}"
        })

    except Exception as e:
        logger.error(f"Pipeline Error: {e}", exc_info=True)
        await manager.send_json(websocket, {"status": "error", "message": str(e)})
    finally:
        manager.disconnect(websocket)

# --- Static Files and Root ---
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/tts_output", StaticFiles(directory=TTS_OUTPUT_DIR), name="tts_output")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    return FileResponse(FRONTEND_DIR / 'index.html')