# app/main.py
import os
import asyncio
import logging
import shutil
import json
import re
import ast
from pathlib import Path
from typing import Optional
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
    genai.configure(api_key=GEMINI_API_KEY)
    # Use the powerful model for initial script creation
    script_model = genai.GenerativeModel('gemini-2.5-pro')
    # Use a faster, more cost-effective model for debugging iterations
    debugging_model = genai.GenerativeModel('gemini-2.5-flash')
except KeyError:
    logger.warning("GEMINI_API_KEY not set. AI features will be unavailable.")
    tts_service = None
    script_model = None
    debugging_model = None

BASE_DIR = Path("/manim")
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
FRONTEND_DIR = BASE_DIR / "frontend"
TTS_OUTPUT_DIR = BASE_DIR / "tts_output"
MEDIA_DIR = BASE_DIR / "media"

for directory in [OUTPUT_DIR, TEMP_DIR, FRONTEND_DIR, TTS_OUTPUT_DIR, MEDIA_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections = set()
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
    async def send_json(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.warning(f"Could not send to websocket: {e}")

manager = ConnectionManager()

# --- Helper Functions ---
async def send_progress(websocket: WebSocket, stage: str, message: str, status: str = "progress"):
    await manager.send_json(websocket, {"status": status, "stage": stage, "message": message})

def ultimate_json_parser(s: str) -> dict:
    json_match = re.search(r'\{.*\}', s, re.DOTALL)
    if not json_match:
        if "from manim import" in s:
            logger.warning("AI returned raw code instead of JSON. Wrapping it now.")
            escaped_script = s.replace('\\', '\\\\').replace('"', '\"').replace('\n', '\\n')
            return json.loads(f'{{"script": "{escaped_script}"}}')
        raise ValueError("Could not find a valid JSON object or raw script in the response.")
    json_str = json_match.group(0)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning("Initial JSON parsing failed. Attempting to fix newlines...")
        json_str_fixed = re.sub(r'(?<!\\)\n', '\\n', json_str)
        return json.loads(json_str_fixed)

# --- AI Agents ---
async def syntax_validation_agent(script_content: str) -> Optional[str]:
    try:
        ast.parse(script_content)
        return None
    except (SyntaxError, IndentationError) as e:
        return f"{type(e).__name__}: {e}. Please fix the syntax."
    except Exception as e:
        return f"An unexpected syntax-related error occurred: {e}"

async def narration_agent(topic: str, websocket: WebSocket) -> str:
    await send_progress(websocket, "AI Agent: Narrator", "Generating narration script...")
    prompt = f'You are a professional scriptwriter for educational videos. Your task is to write a clear, concise, and engaging narration script for an animation explaining the topic: "{topic}". The total speaking time should be approximately 1 minute and 45 seconds. Focus on clarity and a logical flow. Do not include any other text, formatting, or JSON structure. Your output should be only the raw text of the narration.'
    if not script_model: raise Exception("Script generation model is not configured.")
    response = await script_model.generate_content_async(prompt)
    narration_text = response.text.strip()
    await send_progress(websocket, "AI Agent: Narrator", "Narration script generated successfully.")
    await manager.send_json(websocket, {"narration": narration_text})
    return narration_text

async def manim_scripting_agent(topic: str, narration: str, websocket: WebSocket, error_message: str = None, original_script: str = None) -> str:
    scene_name = topic.replace(" ", "").capitalize()
    if error_message and original_script:
        await send_progress(websocket, "AI Agent: Manim Scripter", "Sending script back to the AI for debugging...")
        prompt = f"""You are an expert Manim scriptwriter and debugger for Manim v0.19.0. Your primary goal is to create an animation that *clarifies* the topic. The following script you wrote has failed with an error. You must fix it, ensuring the corrected code still provides a clear and relevant visual explanation for the narration.

**The original goal was to create an animation for this narration:**
---
{narration}
---
**Error Message:**
---
{error_message}
---
**Original Faulty Script:**
---
{original_script}
---
**Instructions:**
1. Analyze the error message and the script to find the problem.
2. Provide a corrected, complete, and runnable version of the script that still visually represents the narration.
3. The final output must be a single, raw JSON object with one key: "script"."""
        model_to_use = debugging_model
        if not model_to_use: raise Exception("Debugging model is not configured.")
    else:
        await send_progress(websocket, "AI Agent: Manim Scripter", "Generating Manim script based on narration...")
        prompt = f"""You are an expert Manim scriptwriter and visual educator for Manim v0.19.0. Your primary goal is to create an animation that *clarifies* the topic. The visuals must be directly relevant to the words being spoken. First, create a step-by-step visual storyboard plan. For each part of the narration, decide on the most effective and simple visual representation. Once you have a clear plan, write the Manim script to execute it.

The final output must be a single, raw JSON object containing one key: "script".

**Narration to Animate:**
---
{narration}
---
**Layout and Scene Management Rules:**
1. **CRITICAL: No Overlapping.** Elements must not overlap. Before adding new elements, clear the screen of previous, unrelated elements using `self.play(*[FadeOut(mob) for mob in self.mobjects])`.
2. **Stay On Screen.** All text and animations must be clearly visible and stay within the frame. Use `.scale()` to make objects or text smaller if they are too large.
3. **Position Intelligently.** Use relative positioning like `.to_edge()`, `.next_to()`, and `.shift()` to arrange elements. Avoid hardcoding `(x, y, z)` coordinates.
4. **Group Related Objects.** Use `VGroup` to group objects that belong together. This makes them easier to manage and animate.
5. **Logical Flow.** The visuals must logically follow the narration. Clear the screen when the narration moves to a new topic.
6. **Forbidden Techniques.** Do NOT use `SVGMobject` with raw SVG data. Do NOT use any rate functions (e.g., `rate_func=ease_in_quad`).

**Instructions:**
1. The Scene class must be named `{scene_name}`.
2. The animation's total duration (including all `self.wait()` calls) should be approximately 120 seconds to match the narration.
3. Use simple and clear visuals. Prioritize fundamental Manim objects (`Circle`, `Square`, `Text`, `Line`) and animations (`Create`, `Write`, `Transform`, `FadeIn`, `FadeOut`).
4. Do not use complex or external libraries. The script must be self-contained.
5. The JSON output must be clean, without any markdown, comments, or extra text."""
        model_to_use = script_model
        if not model_to_use: raise Exception("Script generation model is not configured.")

    response = await model_to_use.generate_content_async(prompt)
    raw_response_text = response.text
    logger.info(f"Raw Manim script AI response: {raw_response_text}")
    try:
        content = ultimate_json_parser(raw_response_text)
        script_content = content["script"]
    except (ValueError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to decode or find 'script' key in JSON: {raw_response_text}")
        raise Exception(f"Failed to process the AI's JSON response for the script. Error: {e}")

    if error_message:
        await send_progress(websocket, "AI Agent: Manim Scripter", "AI has returned a new version of the script.")
    else:
        await send_progress(websocket, "AI Agent: Manim Scripter", "Manim script generated successfully.")
    await manager.send_json(websocket, {"script": script_content})
    return script_content

async def run_manim_websockets(websocket: WebSocket, script_path: str, scene_name: str, quality: str) -> str:
    try:
        await send_progress(websocket, "Manim", f"Starting Manim rendering ({quality})...")
        quality_flags = {"low_quality": "-ql", "medium_quality": "-qm", "high_quality": "-qh", "production_quality": "-qk"}
        cmd = ["manim", quality_flags.get(quality, "-ql"), "--media_dir", str(OUTPUT_DIR), script_path, scene_name]
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        stdout_str, stderr_str = stdout.decode().strip(), stderr.decode().strip()
        if stdout_str:
            logger.info(f"Manim stdout:\n{stdout_str}")
            await send_progress(websocket, "Manim Log", stdout_str)
        if stderr_str:
            logger.error(f"Manim stderr:\n{stderr_str}")
            await send_progress(websocket, "Manim Log", stderr_str)
        if process.returncode != 0:
            raise Exception(stderr_str or "Manim rendering failed with an unknown error.")
        video_path_match = re.search(r"File saved at '(.*?)'", stdout_str)
        if not video_path_match:
            raise FileNotFoundError("Could not find the Manim output file path in the logs.")
        return video_path_match.group(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred during Manim execution: {e}", exc_info=True)
        raise e

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
    generation_task = None
    
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "start":
                if generation_task:
                    await send_progress(websocket, "Error", "A generation task is already in progress.", status="error")
                    continue
                topic = data.get("topic", "Default Topic")
                quality = data.get("quality", "low_quality")
                voice = data.get("voice", "Puck")
                generation_task = asyncio.create_task(
                    run_generation_pipeline(websocket, topic, quality, voice)
                )
            elif data.get("type") == "stop":
                if generation_task and not generation_task.done():
                    generation_task.cancel()
                    await send_progress(websocket, "Cancelled", "The generation process has been stopped by the user.", status="completed")
                else:
                    await send_progress(websocket, "Info", "No active generation task to stop.")
    except WebSocketDisconnect:
        logger.info("Client disconnected.")
        if generation_task and not generation_task.done():
            generation_task.cancel()
    except Exception as e:
        logger.error(f"An unexpected error occurred in the WebSocket handler: {e}", exc_info=True)
    finally:
        manager.disconnect(websocket)

async def run_generation_pipeline(websocket: WebSocket, topic: str, quality: str, voice: str):
    try:
        scene_name = topic.replace(" ", "").capitalize()
        narration_text = await narration_agent(topic, websocket)
        current_script_content = await manim_scripting_agent(topic, narration_text, websocket)
        
        if not tts_service: raise Exception("TTS Service is not configured.")
        tts_request = TTSRequest(text=narration_text, voice=voice)
        tts_response = await tts_service.generate_speech(tts_request)
        tts_audio_url = f"/tts_output/{Path(tts_response.audio_path).name}"
        await manager.send_json(websocket, {"tts_audio_url": tts_audio_url})

        max_retries = 10
        video_path_no_audio = None
        for attempt in range(max_retries):
            syntax_error = await syntax_validation_agent(current_script_content)
            if syntax_error:
                await send_progress(websocket, "Linter Agent", f"Syntax error found: {syntax_error}")
                current_script_content = await manim_scripting_agent(
                    topic, narration_text, websocket, error_message=syntax_error, original_script=current_script_content
                )
                continue

            await send_progress(websocket, "Syncing", f"Applying audio synchronization (Attempt {attempt + 1})...")
            synced_script_content = AnimationVoiceSync.generate_synced_manim_script(current_script_content, tts_response)
            synced_script_path = TEMP_DIR / f"{scene_name}_synced_script_attempt_{attempt + 1}.py"
            synced_script_path.write_text(synced_script_content)
            
            try:
                await send_progress(websocket, "Manim", f"Starting rendering attempt #{attempt + 1}...")
                video_path_no_audio = await run_manim_websockets(websocket, str(synced_script_path), scene_name, quality)
                await send_progress(websocket, "Manim", "Rendering successful!")
                break
            except Exception as e:
                error_message = str(e)
                await send_progress(websocket, "Manim", f"Rendering attempt #{attempt + 1} failed.")
                if attempt < max_retries - 1:
                    current_script_content = await manim_scripting_agent(
                        topic, narration_text, websocket, error_message=error_message, original_script=current_script_content
                    )
                else:
                    await send_progress(websocket, "Error", "All rendering attempts failed.", status="error")
                    raise Exception("Exceeded maximum rendering retries.")

        if not video_path_no_audio:
            raise Exception("Failed to render video after debugging attempts.")

        await send_progress(websocket, "FFmpeg", "Combining final video and audio...")
        final_video_path = await combine_audio_video(
            video_path_no_audio, tts_response.audio_path, OUTPUT_DIR / f"{scene_name}_final.mp4"
        )
        await manager.send_json(websocket, {"status": "completed", "output_file": f"/output/{Path(final_video_path).name}"})

    except asyncio.CancelledError:
        logger.info("Generation pipeline was cancelled.")
    except Exception as e:
        logger.error(f"Pipeline Error: {e}", exc_info=True)
        await manager.send_json(websocket, {"status": "error", "message": str(e)})

# --- Static Files and Root ---
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/tts_output", StaticFiles(directory=TTS_OUTPUT_DIR), name="tts_output")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / 'index.html')
