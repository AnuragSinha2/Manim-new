import asyncio
import json
import logging
import os
import re
import subprocess
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import google.generativeai as genai
import hashlib
from moviepy.editor import VideoFileClip, AudioFileClip

# --- Configuration ---
class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(BASE_DIR, 'frontend')
    OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
    TTS_OUTPUT_DIR = os.path.join(BASE_DIR, 'tts_output')
    TEMP_DIR = os.path.join(BASE_DIR, 'temp')
    MEDIA_DIR = os.path.join(BASE_DIR, 'media')
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- TTS Provider ---
class GoogleTTSProvider:
    async def generate_tts(self, text: str, voice: str) -> bytes:
        dummy_wav_header = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00\xfa\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
        return dummy_wav_header

# --- TTS Service ---
class TTSService:
    def __init__(self, tts_provider):
        self.tts_provider = tts_provider
        self.output_dir = Config.TTS_OUTPUT_DIR
        os.makedirs(self.output_dir, exist_ok=True)

    async def generate_audio(self, narration: str, voice: str) -> str:
        narration_hash = hashlib.sha1(narration.encode()).hexdigest()
        output_filename = f"tts_{narration_hash}_{voice}.wav"
        output_path = os.path.join(self.output_dir, output_filename)
        if not os.path.exists(output_path):
            audio_content = await self.tts_provider.generate_tts(narration, voice)
            with open(output_path, 'wb') as f:
                f.write(audio_content)
        return output_path

    @staticmethod
    def combine_audio_with_video(video_path: str, audio_path: str, output_path: str):
        try:
            video_clip = VideoFileClip(video_path)
            audio_clip = AudioFileClip(audio_path)
            final_clip = video_clip.set_audio(audio_clip)
            final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")
        finally:
            if 'video_clip' in locals():
                video_clip.close()
            if 'audio_clip' in locals():
                audio_clip.close()
            if 'final_clip' in locals():
                final_clip.close()

# --- FastAPI App and Services ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI()
google_tts_provider = GoogleTTSProvider()
tts_service = TTSService(google_tts_provider)

# --- AI Model Configuration ---
genai.configure(api_key=Config.GEMINI_API_KEY)
generation_config = {"temperature": 0.7, "top_p": 1, "top_k": 1, "max_output_tokens": 8192}
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]
script_model = genai.GenerativeModel(
    model_name="gemini-2.5-pro",
    generation_config=generation_config,
    safety_settings=safety_settings
)

# --- Helper Functions ---
async def send_progress(websocket: WebSocket, stage: str, message: str, additional_data: dict = None):
    data = {"status": "progress", "stage": stage, "message": message}
    if additional_data:
        data.update(additional_data)
    await websocket.send_text(json.dumps(data))

def clean_json_response(raw_text: str) -> dict:
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
    if not json_match:
        json_match = re.search(r'(\{.*?\})', raw_text, re.DOTALL)
    if not json_match:
        raise ValueError("Could not find a valid JSON object in the response.")
    cleaned_text = json_match.group(1)
    return json.loads(cleaned_text)

# --- AI Agents ---
async def narration_agent(topic: str, websocket: WebSocket) -> str:
    await send_progress(websocket, "Narration", "Generating narration script...")
    prompt = f'You are a scriptwriter. Your task is to write a concise and engaging narration for a short video explaining the topic: "{topic}". The narration should be clear, easy to understand, and directly explain the concept. Do not include any timestamps, formatting (like markdown), or any other extra information. The output should be only the plain text of the narration.'
    response = await script_model.generate_content_async(prompt)
    narration = response.text.strip()
    await send_progress(websocket, "Narration", "Narration script generated.", {"narration": narration})
    return narration

async def synchronization_agent(narration: str, websocket: WebSocket) -> list:
    await send_progress(websocket, "Synchronization", "Generating synchronization data...")
    prompt = f'You are a video editor. Here is a narration script for an animation:\n---\n{narration}\n---\nYour task is to break this narration into logical segments for animation scenes. For each segment, provide the text and estimate a duration in seconds. The output MUST be a single, raw JSON object with a "scenes" key, containing a list of objects. Each object in the list should have three keys: "scene_number", "text", and "duration".\nExample format:\n{{\n  "scenes": [\n    {{\n      "scene_number": 1,\n      "text": "First part of the narration.",\n      "duration": 5\n    }},\n    {{\n      "scene_number": 2,\n      "text": "Second part of the narration.",\n      "duration": 8\n    }}\n  ]\n}}'
    response = await script_model.generate_content_async(prompt)
    try:
        sync_data = clean_json_response(response.text)
        if 'scenes' not in sync_data or not isinstance(sync_data['scenes'], list):
            raise ValueError("Invalid sync data format.")
        return sync_data['scenes']
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse sync data: {e}\nResponse was: {response.text}")
        raise

async def manim_scripting_agent(topic: str, narration: str, sync_data: list, websocket: WebSocket) -> str:
    await send_progress(websocket, "Manim Scripting", "Generating Manim script...")
    scene_name = topic.replace(" ", "").capitalize()
    prompt = f'You are a Manim expert specializing in Manim v0.19.0. Your task is to create a Manim script for a video based on the provided narration and scene structure.\n\nTopic: {topic}\nNarration:\n---\n{narration}\n---\nScene Structure (with durations in seconds):\n---\n{json.dumps(sync_data, indent=2)}\n---\n\n**CRITICAL INSTRUCTIONS:**\n1.  Create a **single Manim scene** named `{scene_name}`.\n2.  The entire animation should happen within this single scene.\n3.  For each scene in the structure, create corresponding animations.\n4.  The duration of each animation block (including `self.wait()` calls) MUST match the `duration` for that scene.\n5.  Use the `text` from the scene structure to create `Text` or `MathTex` objects.\n6.  Ensure the visual elements clearly explain the narration segment.\n7.  The scene background must be white. Add `self.camera.background_color = WHITE` in the `construct` method.\n8.  The output MUST be a single, raw JSON object with a "script" key containing the Python code as a single string.\n    Example: {{"script": "from manim import *\\n\\nclass MyScene(Scene):\\n    def construct(self):\\n        ..."}}'
    response = await script_model.generate_content_async(prompt)
    try:
        script_data = clean_json_response(response.text)
        return script_data['script']
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse script data: {e}\nResponse was: {response.text}")
        raise

async def debugging_agent(script: str, error_message: str, websocket: WebSocket) -> str:
    await send_progress(websocket, "Debugging", "Attempting to fix Manim script...")
    prompt = f'You are a Manim debugging expert for Manim v0.19.0. The following Manim script failed with an error. Please fix the script.\n\n**Error Message:**\n---\n{error_message}\n---\n\n**Original Script:**\n---\n{script}\n---\n\nProvide only the corrected, complete Python code for the script inside a single JSON object with the key "script".\nExample: {{"script": "from manim import *\\n\\nclass FixedScene(Scene):\\n    def construct(self):\\n        # ... corrected code ..."}}'
    response = await script_model.generate_content_async(prompt)
    try:
        script_data = clean_json_response(response.text)
        await send_progress(websocket, "Debugging", "Script fixed. Retrying rendering.")
        return script_data['script']
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse fixed script data: {e}\nResponse was: {response.text}")
        raise

# --- Main WebSocket Handler ---
@app.websocket("/ws/generate-full-animation")
async def generate_full_animation(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_text()
        payload = json.loads(data)
        topic = payload['topic']
        quality = payload.get('quality', 'medium_quality')
        voice = payload.get('voice', 'Puck')

        narration = await narration_agent(topic, websocket)
        audio_filepath = await tts_service.generate_audio(narration, voice)
        await send_progress(websocket, "TTS", "Narration audio generated.", {"tts_audio_url": f"/tts_output/{os.path.basename(audio_filepath)}"})
        sync_data = await synchronization_agent(narration, websocket)
        manim_script = await manim_scripting_agent(topic, narration, sync_data, websocket)
        await send_progress(websocket, "Manim Scripting", "Manim script generated.", {"script": manim_script})

        max_retries = 3
        final_video_path = None
        for attempt in range(max_retries):
            try:
                await send_progress(websocket, "Rendering", f"Starting rendering (Attempt {attempt + 1}/{max_retries})...")
                scene_name = topic.replace(" ", "").capitalize()
                script_filename = f"{scene_name}_script.py"
                script_filepath = os.path.join(Config.TEMP_DIR, script_filename)
                with open(script_filepath, "w") as f:
                    f.write(manim_script)

                quality_flags = {"low_quality": "-ql", "medium_quality": "-qm", "high_quality": "-qh", "production_quality": "-qk"}
                quality_flag = quality_flags.get(quality, "-qm")
                command = ["manim", quality_flag, script_filepath, scene_name]
                
                process = await asyncio.create_subprocess_exec(*command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    await send_progress(websocket, "Rendering", "Rendering successful.")
                    
                    video_dir_name = script_filename.replace('.py', '')
                    quality_dir_name = '480p15'
                    if quality == 'medium_quality':
                        quality_dir_name = '720p30'
                    elif quality == 'high_quality':
                        quality_dir_name = '1080p60'
                    elif quality == 'production_quality':
                        quality_dir_name = '2160p60'

                    video_dir = os.path.join(Config.MEDIA_DIR, 'videos', video_dir_name, quality_dir_name)
                    output_files = [f for f in os.listdir(video_dir) if f.endswith('.mp4')]
                    if not output_files:
                        raise FileNotFoundError(f"Manim output video not found in {video_dir}!")
                    
                    video_filename = output_files[0]
                    video_path_without_audio = os.path.join(video_dir, video_filename)

                    await send_progress(websocket, "Combining", "Combining video and audio...")
                    combined_video_filename = f"{scene_name}_final.mp4"
                    combined_video_path = os.path.join(Config.OUTPUT_DIR, combined_video_filename)
                    
                    TTSService.combine_audio_with_video(video_path_without_audio, audio_filepath, combined_video_path)
                    
                    final_video_path = f"/output/{combined_video_filename}"
                    await send_progress(websocket, "Completed", "Animation complete!", {"output_file": final_video_path})
                    break
                else:
                    error_message = stderr.decode()
                    logger.error(f"Manim rendering failed:\n{error_message}")
                    await send_progress(websocket, "Error", f"Rendering failed on attempt {attempt + 1}.")
                    if attempt < max_retries - 1:
                        manim_script = await debugging_agent(manim_script, error_message, websocket)
                        await send_progress(websocket, "Debugging", "Retrying with fixed script.", {"script": manim_script})
                    else:
                        raise Exception("Exceeded max retries for Manim rendering.")
            except Exception as e:
                logger.error(f"An error occurred during rendering attempt {attempt + 1}: {e}")
                if attempt >= max_retries - 1:
                    raise e
        if not final_video_path:
            raise Exception("Failed to generate video after all retries.")
    except WebSocketDisconnect:
        logger.info("Client disconnected.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        error_message = json.dumps({"status": "error", "message": str(e)})
        await websocket.send_text(error_message)
    finally:
        if websocket.client_state != 'DISCONNECTED':
            await websocket.close()

# --- Static Files ---
app.mount("/static", StaticFiles(directory=Config.STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=Config.OUTPUT_DIR), name="output")
app.mount("/tts_output", StaticFiles(directory=Config.TTS_OUTPUT_DIR), name="tts_output")

@app.get("/")
async def read_root():
    return {"message": "Welcome to Manim AI Explainer"}