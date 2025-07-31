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
    version="2.5.0"
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

# --- Manim Layout Manager ---
LAYOUT_MANAGER_CODE = """
from manim import VGroup, UP, DOWN, LEFT, RIGHT

class LayoutManager:
    def __init__(self, scene):
        self.scene = scene
        self.objects = {}
        self.regions = {
            'TOP': UP * 3.5,
            'CENTER': [0, 0, 0],
            'BOTTOM': DOWN * 3.5,
            'LEFT': LEFT * 6,
            'RIGHT': RIGHT * 6,
            'TOP_LEFT': UP * 3.5 + LEFT * 6,
            'TOP_RIGHT': UP * 3.5 + RIGHT * 6,
            'BOTTOM_LEFT': DOWN * 3.5 + LEFT * 6,
            'BOTTOM_RIGHT': DOWN * 3.5 + RIGHT * 6,
        }

    def place(self, mobject, region, buff=0.5):
        if region not in self.regions:
            print(f"Warning: Region '{region}' not found. Placing at center.")
            region = 'CENTER'
        
        mobject.move_to(self.regions[region])
        self.objects[str(id(mobject))] = mobject
        return mobject

    def next_to(self, mobject, target_mobject, direction, buff=0.5):
        mobject.next_to(target_mobject, direction, buff=buff)
        self.objects[str(id(mobject))] = mobject
        return mobject

    def get_all_mobjects(self, except_list=None):
        if except_list is None:
            except_list = []
        return [m for m in self.scene.mobjects if m not in except_list]
"""

# --- Custom Exceptions ---
class ManimRenderingError(Exception):
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

def clean_ai_response(raw_text: str) -> str:
    raw_text = raw_text.replace('–', '-')
    raw_text = raw_text.replace('“', '"')
    raw_text = raw_text.replace('”', '"')
    raw_text = raw_text.replace('‘', "'")
    raw_text = raw_text.replace('’', "'")
    return raw_text

# --- AI Agents ---
async def send_progress(websocket: WebSocket, stage: str, message: str, status: str = "progress"):
    await manager.send_json(websocket, {"status": status, "stage": stage, "message": message})

async def narration_agent(topic: str, websocket: WebSocket) -> Optional[Dict]:
    await send_progress(websocket, "AI Narrator", "Generating narration and timings...")
    prompt = f"""
    You are an expert instructional designer. For the topic "{topic}", generate a JSON object with:
    1.  `"narration"`: A clear, concise narration script.
    2.  `"animation_markers"`: A list of dictionaries with "name" and cumulative "time" in seconds for key narration points.

    Example:
    {{
        "narration": "The Pythagorean Theorem relates the sides of a right triangle. The formula is a squared plus b squared equals c squared.",
        "animation_markers": [
            {{"name": "Title", "time": 0.0}},
            {{"name": "Formula", "time": 4.0}}
        ]
    }}
    """
    if not debug_model: raise Exception("Debug model not configured.")
    try:
        response = await debug_model.generate_content_async(prompt)
        cleaned_text = clean_ai_response(response.text)
        json_string = cleaned_text.strip().split("```json\n")[1].split("```")[0]
        ai_content = json.loads(json_string)
        if "narration" not in ai_content or "animation_markers" not in ai_content:
            raise Exception("AI did not return valid narration/markers.")
        await send_progress(websocket, "AI Narrator", "Narration generated.")
        return ai_content
    except Exception as e:
        logger.error(f"AI Narration failed: {e}")
        return {"narration": "AI script generator failed.", "animation_markers": []}

async def showrunner_agent(narration: str, animation_markers: list, websocket: WebSocket) -> list:
    await send_progress(websocket, "AI Showrunner", "Designing visual scenes...")
    scenes_with_text = []
    narration_lines = [line.strip() for line in narration.split('.') if line.strip()]
    for i, marker in enumerate(animation_markers):
        scenes_with_text.append({
            "scene_number": i + 1,
            "marker_name": marker["name"],
            "duration": (animation_markers[i+1]['time'] - marker['time']) if i + 1 < len(animation_markers) else 3.0,
            "text": narration_lines[i] if i < len(narration_lines) else ""
        })

    prompt = f"""
    You are a creative director. For each scene, provide `visual_instructions` and an optional `clear_screen` flag.
    **CRITICAL**: Use the `layout` object for all positioning. Do not set positions manually.

    **Available Layout Regions**: `TOP`, `CENTER`, `BOTTOM`, `LEFT`, `RIGHT`, `TOP_LEFT`, `TOP_RIGHT`, `BOTTOM_LEFT`, `BOTTOM_RIGHT`.
    **Available Layout Methods**: `layout.place(mobject, 'REGION')`, `layout.next_to(mobject, target, DIRECTION)`.

    **Scenes:**
    ---
    {json.dumps(scenes_with_text, indent=2)}
    ---

    **Output Format (JSON with a "scenes" key):**
    {{
      "scenes": [
        {{
          "scene_number": 1,
          "visual_instructions": "Create a title object named 'title'. Use `layout.place(title, 'TOP')`. Animate with `Write`."
        }},
        {{
          "scene_number": 2,
          "clear_screen": true,
          "visual_instructions": "Create a blue triangle named 'tri'. Use `layout.place(tri, 'CENTER')`..."
        }}
      ]
    }}
    """
    if not debug_model: raise Exception("Debug model not configured.")
    try:
        response = await debug_model.generate_content_async(prompt)
        cleaned_text = clean_ai_response(response.text)
        json_string = cleaned_text.strip().split("```json\n")[1].split("```")[0]
        showrunner_directions = json.loads(json_string)
        if "scenes" not in showrunner_directions: raise Exception("Invalid showrunner format.")
        
        for i, scene in enumerate(scenes_with_visuals):
            if i < len(showrunner_directions['scenes']):
                scene_data = showrunner_directions['scenes'][i]
                scene['visual_instructions'] = scene_data.get('visual_instructions', '')
                if scene_data.get('clear_screen'):
                    scene['clear_screen'] = True
        
        await send_progress(websocket, "AI Showrunner", "Visuals designed.")
        return scenes_with_visuals
    except Exception as e:
        logger.error(f"AI Showrunner failed: {e}")
        return scenes_with_visuals

async def manim_scripting_agent(topic: str, scenes_with_visuals: list, websocket: WebSocket) -> str:
    await send_progress(websocket, "AI Animator", "Writing Manim code...")
    prompt = f"""
    You are a Manim code generator. Write a complete Manim script by precisely following the storyboard.

    **Topic:** {topic}
    **Storyboard:**
    ---
    {json.dumps(scenes_with_visuals, indent=2)}
    ---

    **CRITICAL INSTRUCTIONS:**
    1.  **Use the LayoutManager**: At the start of `construct`, you MUST initialize the layout manager: `layout = LayoutManager(self)`.
    2.  **ONLY Use LayoutManager for Positioning**: For all positioning, you MUST use the methods described in the `visual_instructions`, like `layout.place()` or `layout.next_to()`. Do not use `.move_to()`, `.to_edge()`, etc.
    3.  **Clear Screen on Command**: If `"clear_screen": true`, you MUST call `layout.get_all_mobjects()` and fade them out.
    4.  **Match Durations**: The animations and waits in each scene block MUST add up to the `duration` for that scene.
    5.  **Single Scene Class**: Create one scene named `{topic.replace(" ", "")}`.

    **Output Format (JSON with a "script" key):**
    {{
        "script": "from manim import *\\n\\nclass {topic.replace(" ", "")}(Scene):\\n    def construct(self):\\n        layout = LayoutManager(self)\\n        # ... your code here ..."
    }}
    """
    if not generation_model: raise Exception("Generation model not configured.")
    try:
        response = await generation_model.generate_content_async(prompt)
        cleaned_text = clean_ai_response(response.text)
        json_string = cleaned_text.strip().split("```json\n")[1].split("```")[0]
        script_data = json.loads(json_string)
        if "script" not in script_data: raise Exception("Invalid script format.")
        await send_progress(websocket, "AI Animator", "Manim script generated.")
        return script_data['script']
    except Exception as e:
        logger.error(f"AI Scripting failed: {e}")
        return f"from manim import *\\n\\nclass {topic.replace(' ', '')}(Scene):\\n    def construct(self):\\n        self.add(Text('AI Script Generation Failed', color=RED))"

async def debug_manim_script(original_script: str, error_log: str, websocket: WebSocket) -> str:
    await send_progress(websocket, "AI Debugging", "Attempting to fix script...")
    prompt = f"""
    The Manim script failed with an error. Please fix it.
    **Error:**
    ---
    {error_log}
    ---
    **Original Script:**
    ---
    {original_script}
    ---
    Provide only the corrected, complete Python code in a single JSON object with the key "script".
    """
    if not debug_model: raise Exception("Debug model not configured.")
    try:
        response = await debug_model.generate_content_async(prompt)
        cleaned_text = clean_ai_response(response.text)
        json_string = cleaned_text.strip().split("```json\n")[1].split("```")[0]
        script_data = json.loads(json_string)
        await send_progress(websocket, "AI Debugging", "Script fixed. Retrying.")
        return script_data['script']
    except Exception as e:
        logger.error(f"AI Debugging failed: {e}")
        raise Exception(f"AI debugger failed: {e}")

# --- Main Pipeline ---
@app.websocket("/ws/generate-full-animation")
async def ws_generate_full_animation(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        data = await websocket.receive_json()
        if data.get("type") == "start":
            topic = data.get("topic")
            if not topic:
                await send_progress(websocket, "Error", "Topic is required.", status="error")
                return
            task = asyncio.create_task(
                full_animation_pipeline(websocket, topic, data.get("quality", "low_quality"), data.get("voice", "Puck"))
            )
            manager.assign_task(websocket, task)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        await send_progress(websocket, "Error", str(e), status="error")
        manager.disconnect(websocket)

async def full_animation_pipeline(websocket: WebSocket, topic: str, quality: str, voice: str):
    script_content = None
    try:
        scene_name = topic.replace(" ", "")
        
        # 1. AI agents generate content
        narration_content = await narration_agent(topic, websocket)
        narration_text = narration_content["narration"]
        animation_markers = narration_content["animation_markers"]
        await manager.send_json(websocket, {"narration": narration_text})

        scenes_with_visuals = await showrunner_agent(narration_text, animation_markers, websocket)
        script_content = await manim_scripting_agent(topic, scenes_with_visuals, websocket)
        
        # Inject LayoutManager code into the script
        final_script = LAYOUT_MANAGER_CODE + "\n" + script_content
        await manager.send_json(websocket, {"script": final_script})

        # 2. TTS and Sync
        if not tts_service: raise Exception("TTS Service not configured.")
        scene_duration = max(marker['time'] for marker in animation_markers) if animation_markers else 0
        tts_request = TTSRequest(text=narration_text, script=final_script, voice=voice, scene_duration=scene_duration, animation_markers=animation_markers)
        tts_response = await tts_service.generate_speech(tts_request)
        
        if tts_response.sync_data:
            final_script = AnimationVoiceSync.generate_synced_manim_script(final_script, tts_response)
            await manager.send_json(websocket, {"script": final_script})
        
        script_path = TEMP_DIR / f"{scene_name}_script.py"
        script_path.write_text(final_script)

        # 3. Render and Combine
        max_render_attempts = 10
        for attempt in range(max_render_attempts):
            try:
                await send_progress(websocket, "Manim", f"Rendering (Attempt {attempt + 1}/{max_render_attempts})...")
                video_path_no_audio = await run_manim_websockets(websocket, str(script_path), scene_name, quality)
                await send_progress(websocket, "Manim", "Rendering successful!")
                
                final_video_path = await combine_audio_video(video_path_no_audio, tts_response.audio_path, OUTPUT_DIR / f"{scene_name}_final.mp4")
                
                await manager.send_json(websocket, {"status": "completed", "output_file": f"/output/{Path(final_video_path).name}"})
                return
            except ManimRenderingError as e:
                logger.error(f"Manim rendering failed on attempt {attempt + 1}. Error:\n{e.error_log}")
                if attempt >= max_render_attempts - 1:
                    raise e
                final_script = await debug_manim_script(final_script, e.error_log, websocket)
                script_path.write_text(final_script)
                await manager.send_json(websocket, {"script": final_script})
        
        raise Exception("Failed to render video after all attempts.")

    except asyncio.CancelledError:
        await send_progress(websocket, "Cancelled", "Animation generation was cancelled.")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        await send_progress(websocket, "Error", f"An error occurred: {e}", status="error")

async def run_manim_websockets(websocket: WebSocket, script_path: str, scene_name: str, quality: str) -> str:
    quality_flags = {"low_quality": "-ql", "medium_quality": "-qm", "high_quality": "-qh", "production_quality": "-qk"}
    cmd = ["manim", quality_flags.get(quality, "-ql"), "--media_dir", str(OUTPUT_DIR), script_path, scene_name]
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    
    async def stream_logs(stream, log_prefix, capture_list):
        while True:
            line = await stream.readline()
            if not line: break
            message = line.decode().strip()
            capture_list.append(message)
            await send_progress(websocket, f"Manim {log_prefix}", message)
    
    stdout_capture, stderr_capture = [], []
    await asyncio.gather(
        stream_logs(process.stdout, "stdout", stdout_capture),
        stream_logs(process.stderr, "stderr", stderr_capture)
    )
    await process.wait()

    if process.returncode != 0:
        raise ManimRenderingError("Manim rendering failed", "\n".join(stderr_capture))

    # Find the output file
    expected_path_fragment = os.path.join("videos", Path(script_path).stem)
    for line in stdout_capture:
        if ".mp4" in line and expected_path_fragment in line:
            # Manim's output path is relative to the media_dir
            relative_path = line.split(":")[-1].strip()
            return str(OUTPUT_DIR / relative_path)
    raise FileNotFoundError(f"Could not find Manim output file path in logs.")

async def combine_audio_video(video_path: str, audio_path: str, output_path: Path) -> str:
    cmd = ["ffmpeg", "-i", video_path, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-shortest", "-y", str(output_path)]
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise Exception(f"FFmpeg failed: {stderr.decode()}")
    return str(output_path)

# --- Static Files and Root ---
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend")), name="static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
