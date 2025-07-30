# app/main.py - Enhanced with TTS integration and WebSocket support

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import subprocess
import tempfile
import json
from pathlib import Path
from typing import Optional, List, Dict
import asyncio
import shutil
import logging
import google.generativeai as genai

from tts_service import GeminiTTSService, TTSRequest, TTSResponse, AnimationVoiceSync

# --- Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Manim Animation & TTS API",
    description="Create mathematical animations with synchronized voice-over using Gemini 2.5 Flash TTS",
    version="2.4.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Services and Directories ---
try:
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
    tts_service = GeminiTTSService(GEMINI_API_KEY)
    # Configure the generative AI models
    genai.configure(api_key=GEMINI_API_KEY)
    generation_model = genai.GenerativeModel('gemini-2.5-pro')
    debug_model = genai.GenerativeModel('gemini-2.5-flash')
except KeyError:
    logger.warning("GEMINI_API_KEY not set. TTS and AI features will be unavailable.")
    tts_service = None
    generation_model = None
    debug_model = None

# Directories
BASE_DIR = Path("/manim")
ANIMATIONS_DIR = BASE_DIR / "animations"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
UPLOADS_DIR = BASE_DIR / "uploads"
TTS_OUTPUT_DIR = BASE_DIR / "tts_output"

for directory in [ANIMATIONS_DIR, OUTPUT_DIR, TEMP_DIR, UPLOADS_DIR, TTS_OUTPUT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# --- Custom Exceptions ---
class ManimRenderingError(Exception):
    """Custom exception for Manim rendering failures."""
    def __init__(self, message, error_log):
        super().__init__(message)
        self.error_log = error_log

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[WebSocket, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = None

    def disconnect(self, websocket: WebSocket):
        task = self.active_connections.pop(websocket, None)
        if task and not task.done():
            task.cancel()
            logger.info("Animation task cancelled due to WebSocket disconnect.")

    async def send_json(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.warning(f"Could not send to websocket: {e}")


    def assign_task(self, websocket: WebSocket, task: asyncio.Task):
        self.active_connections[websocket] = task

manager = ConnectionManager()


# --- Helper Functions ---
async def send_progress(websocket: WebSocket, stage: str, message: str, status: str = "progress"):
    await manager.send_json(websocket, {"status": status, "stage": stage, "message": message})

async def generate_ai_script_and_narration(topic: str, websocket: WebSocket) -> Optional[Dict]:
    """Generate a Manim script, narration, and animation markers using an AI model."""
    await send_progress(websocket, "AI Scripting", "AI is generating script, narration, and timing markers...")
    
    prompt = f"""
    You are an expert Manim animator and instructional designer. Your task is to generate a JSON object containing a Manim script, a corresponding narration, and a list of animation markers for a high-quality educational video about the topic: "{topic}".

    The scene class in the script must be named: {topic.replace(" ", "")}

    **Visual Best Practices (Follow these rules carefully):**
    1.  **Screen Boundaries & Layout**: NEVER let any text or animation go off-screen. Avoid overlaps by using `.next_to()`, `.to_edge()`, etc.
    2.  **Text Readability**: Use a clear font size hierarchy (e.g., Title=48, Body=32, Annotations=24).
    3.  **Pacing**: Use `self.wait(n)` to give viewers time to process information.

    **Output Format (Must be a single, raw JSON object):**
    1.  `"script"`: A string containing the complete, runnable Python code for the Manim scene.
    2.  `"narration"`: A string containing the clear, concise narration that matches the animation.
    3.  `"animation_markers"`: A list of dictionaries, where each dictionary has a "name" (str) and a "time" (float, in seconds) corresponding to the start time of a key animation event in the script's timeline. The times should be cumulative.

    **Example for "CircleToSquare":**
    {{
        "script": "from manim import *\n\nclass CircleToSquare(Scene):\n    def construct(self):\n        title = Text(\"Circle to Square\", font_size=48).to_edge(UP)\n        self.play(Write(title))\n        self.wait(1)\n        circle = Circle().scale(2)\n        self.play(Create(circle))\n        self.wait(2)\n        square = Square().scale(2)\n        self.play(Transform(circle, square))\n        self.wait(2)",
        "narration": "First, we display the title. A circle appears. After a moment, it transforms into a square.",
        "animation_markers": [
            {{ "name": "Title Appears", "time": 0.0 }},
            {{ "name": "Circle Appears", "time": 2.0 }},
            {{ "name": "Square Transform", "time": 5.0 }}
        ]
    }}
    """
    
    if not generation_model:
        raise Exception("Generative model is not configured.")

    try:
        response = await generation_model.generate_content_async(prompt)
        json_string = response.text.strip()
        if "```json" in json_string:
            json_string = json_string.split("```json\n")[1].split("```")[0]
        
        ai_content = json.loads(json_string)
        
        if "script" not in ai_content or "narration" not in ai_content or "animation_markers" not in ai_content:
            raise Exception("AI did not return the expected JSON format with script, narration, and markers.")

        await send_progress(websocket, "AI Scripting", "AI content generated successfully.")
        return ai_content
    except Exception as e:
        logger.error(f"AI Scripting failed: {e}")
        return {
            "script": f"from manim import *\n\nclass {topic.replace(' ', '')}(Scene):\n    def construct(self):\n        self.add(Text('AI Script Generation Failed', color=RED))",
            "narration": "I'm sorry, but the AI script generator failed.",
            "animation_markers": []
        }


async def debug_manim_script(original_script: str, error_log: str, websocket: WebSocket) -> str:
    """Uses Gemini 2.5 Flash to debug a Manim script."""
    if not debug_model:
        raise Exception("Debug model is not configured. Cannot fix script.")

    await send_progress(websocket, "AI Debugging", "Manim script failed. Asking AI to fix it...")
    
    prompt = f"""
    The following Manim script failed to render.

    --- SCRIPT ---
    {original_script}
    --- END SCRIPT ---

    Here is the error log from Manim:
    --- ERROR LOG ---
    {error_log}
    --- END ERROR LOG ---

    Please analyze the script and the error log, identify the mistake, and provide the corrected, complete Manim script.
    Do not add any explanations, just output the raw, corrected Python code.
    """
    
    try:
        response = await debug_model.generate_content_async(prompt)
        fixed_script = response.text.strip()
        
        if "```python" in fixed_script:
            fixed_script = fixed_script.split("```python\n")[1].split("```")[0]
        
        await send_progress(websocket, "AI Debugging", "AI has provided a potential fix.")
        logger.info(f"AI provided fixed script:\n{fixed_script}")
        return fixed_script
    except Exception as e:
        logger.error(f"AI Debugging failed: {e}")
        raise Exception(f"The AI debugger failed to generate a fix: {e}")


# --- WebSocket Endpoint ---
@app.websocket("/ws/generate-full-animation")
async def ws_generate_full_animation(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "start":
                topic = data.get("topic")
                quality = data.get("quality", "low_quality")
                voice = data.get("voice", "Puck")
                
                if not topic:
                    await send_progress(websocket, "Error", "Topic is required.", status="error")
                    continue

                task = asyncio.create_task(
                    full_animation_pipeline(websocket, topic, quality, voice)
                )
                manager.assign_task(websocket, task)

            elif message_type == "stop":
                logger.info("Stop request received. Cancelling task.")
                task = manager.active_connections.get(websocket)
                if task and not task.done():
                    task.cancel()
                    await send_progress(websocket, "Cancelled", "Animation generation stopped by user.")
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except asyncio.CancelledError:
        await send_progress(websocket, "Cancelled", "Process cancelled.")
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        await send_progress(websocket, "Error", str(e), status="error")
        manager.disconnect(websocket)


async def full_animation_pipeline(websocket: WebSocket, topic: str, quality: str, voice: str):
    """The complete pipeline from topic to animated video with TTS, with a multi-step debug loop."""
    script_content = None
    try:
        scene_name = topic.replace(" ", "")
        
        # 1. AI generates script, narration, and markers
        ai_content = await generate_ai_script_and_narration(topic, websocket)
        script_content = ai_content["script"]
        narration_text = ai_content["narration"]
        animation_markers = ai_content["animation_markers"]

        await manager.send_json(websocket, {"script": script_content, "narration": narration_text})

        # 2. Generate TTS and Synchronization Data
        if not tts_service:
            raise Exception("TTS Service is not configured.")
        
        scene_duration = max(marker['time'] for marker in animation_markers) if animation_markers else 0
        
        await send_progress(websocket, "TTS", f"Generating voice-over with '{voice}' and calculating sync data...")
        tts_request = TTSRequest(
            text=narration_text, 
            script=script_content,
            voice=voice,
            scene_duration=scene_duration,
            animation_markers=animation_markers
        )
        tts_response = await tts_service.generate_speech(tts_request)
        await send_progress(websocket, "TTS", f"Audio file created at {tts_response.audio_path}")

        # 3. Apply Synchronization to Manim Script
        if tts_response.sync_data:
            await send_progress(websocket, "Sync", "Applying advanced timing synchronization to script...")
            script_content = AnimationVoiceSync.generate_synced_manim_script(script_content, tts_response)
            await manager.send_json(websocket, {"script": script_content}) # Update frontend with synced script
        
        script_path = TEMP_DIR / f"{scene_name}_script.py"
        script_path.write_text(script_content)
        await send_progress(websocket, "File IO", f"Synced script saved to {script_path}")

        # 4. Render animation (with a 3-attempt debugging loop)
        max_render_attempts = 5
        video_path_no_audio = None
        
        for attempt in range(max_render_attempts):
            try:
                await send_progress(websocket, "Manim", f"Starting Manim rendering (Attempt {attempt + 1}/{max_render_attempts})...")
                video_path_no_audio = await run_manim_websockets(
                    websocket, str(script_path), scene_name, quality
                )
                await send_progress(websocket, "Manim", "Manim rendering successful!")
                break
            except ManimRenderingError as e:
                logger.error(f"Manim rendering failed on attempt {attempt + 1}. Error log:\n{e.error_log}")
                if attempt >= max_render_attempts - 1:
                    await send_progress(websocket, "Error", "AI Debugging failed to fix the script.", status="error")
                    raise e
                
                script_content = await debug_manim_script(script_content, e.error_log, websocket)
                script_path.write_text(script_content)
                await manager.send_json(websocket, {"script": script_content})

        if not video_path_no_audio:
            raise Exception("Failed to render video after all attempts.")

        # 5. Combine video and audio
        await send_progress(websocket, "FFmpeg", "Combining video and audio...")
        final_video_path = await combine_audio_video(
            video_path_no_audio, tts_response.audio_path, OUTPUT_DIR / f"{scene_name}_final.mp4"
        )
        await send_progress(websocket, "FFmpeg", f"Final video saved to {final_video_path}")
        
        # 6. Send completion message
        await manager.send_json(websocket, {
            "status": "completed",
            "output_file": f"/output/{Path(final_video_path).name}"
        })

    except asyncio.CancelledError:
        await send_progress(websocket, "Cancelled", "Animation generation was cancelled.")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        await send_progress(websocket, "Error", f"An error occurred: {e}", status="error")


async def run_manim_websockets(
    websocket: WebSocket, script_path: str, scene_name: str, quality: str
) -> str:
    """Run Manim and stream progress over WebSockets."""
    quality_flags = {
        "low_quality": "-ql", "medium_quality": "-qm",
        "high_quality": "-qh", "production_quality": "-qk"
    }
    
    output_filename_base = f"{scene_name}_{quality}"
    
    cmd = [
        "manim", quality_flags.get(quality, "-ql"),
        "--output_file", output_filename_base,
        "--media_dir", str(OUTPUT_DIR),
        script_path, scene_name
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stderr_capture = []

    async def stream_logs(stream, log_prefix, capture_list=None):
        while True:
            line = await stream.readline()
            if not line: break
            message = line.decode().strip()
            if capture_list is not None:
                capture_list.append(message)
            logger.info(f"{log_prefix}: {message}")
            await send_progress(websocket, f"Manim {log_prefix}", message)
    
    await asyncio.gather(
        stream_logs(process.stdout, "stdout"),
        stream_logs(process.stderr, "stderr", stderr_capture)
    )
    await process.wait()

    if process.returncode != 0:
        full_error_log = "\n".join(stderr_capture)
        raise ManimRenderingError(
            f"Manim rendering failed with exit code {process.returncode}",
            error_log=full_error_log
        )

    resolution_map = {"low_quality": "480p15", "medium_quality": "720p30", "high_quality": "1080p60", "production_quality": "2160p60"}
    res_folder = resolution_map.get(quality)
    
    search_dir = OUTPUT_DIR / "videos" / Path(script_path).stem / res_folder
    
    try:
        # The output filename is set by the --output_file flag
        output_file = next(search_dir.glob(f"{output_filename_base}.mp4"))
        return str(output_file)
    except StopIteration:
        raise FileNotFoundError(f"Could not find the Manim output file in {search_dir}")


async def combine_audio_video(video_path: str, audio_path: str, output_path: Path) -> str:
    """Combine video and audio using ffmpeg."""
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-y",
        str(output_path)
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise Exception(f"FFmpeg failed: {stderr.decode()}")
    return str(output_path)


# --- Existing REST Endpoints ---
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(BASE_DIR, "frontend", "index.html"))

# ... (keep all other existing REST endpoints)

# This must be mounted AFTER all other routes to avoid overriding API endpoints
app.mount("/output", StaticFiles(directory="/manim/output"), name="output")
app.mount("/static", StaticFiles(directory="/manim/frontend"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

