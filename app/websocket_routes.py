# app/websockets.py

import asyncio
import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pypdf import PdfReader

from ws_utils import manager, send_progress, send_error
from agents import one_shot_generation_agent, debug_manim_script
from tts_service import GeminiTTSService, TTSRequest
from image_service import ImageService, ImageGenerationError

# --- Setup ---
logger = logging.getLogger(__name__)
router = APIRouter()
tts_service: Optional[GeminiTTSService] = None
image_service: Optional[ImageService] = None
BASE_DIR = Path("/manim")
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"

class ManimRenderingError(Exception):
    def __init__(self, message, error_log):
        super().__init__(message)
        self.error_log = error_log

LAYOUT_MANAGER_CODE = """
from manim import *

class LayoutManager:
    def __init__(self, scene):
        self.scene = scene
        self.objects = {}
        self.regions = {
            'TOP': UP * 3.5, 'CENTER': [0, 0, 0], 'BOTTOM': DOWN * 3.5,
            'LEFT': LEFT * 6, 'RIGHT': RIGHT * 6, 'TOP_LEFT': UP * 3.5 + LEFT * 6,
            'TOP_RIGHT': UP * 3.5 + RIGHT * 6, 'BOTTOM_LEFT': DOWN * 3.5 + LEFT * 6,
            'BOTTOM_RIGHT': DOWN * 3.5 + RIGHT * 6,
        }
    def place(self, mobject, region, buff=0.5):
        mobject.move_to(self.regions.get(region, [0,0,0]))
        self.objects[str(id(mobject))] = mobject
        return mobject
    def next_to(self, mobject, target_mobject, direction, buff=0.5):
        mobject.next_to(target_mobject, direction, buff=buff)
        self.objects[str(id(mobject))] = mobject
        return mobject
    def get_all_mobjects(self, except_list=None):
        if except_list is None: except_list = []
        return [m for m in self.scene.mobjects if m not in except_list]
"""

@router.websocket("/ws/generate-full-animation")
async def generate_full_animation(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "start":
                topic = data.get("topic")
                pdf_path = data.get("pdf_path")
                
                content_input = ""
                is_url_content = False
                scene_name_base = "Animation"

                if pdf_path:
                    await send_progress(websocket, "PDF Processing", "Reading text from PDF...")
                    try:
                        reader = PdfReader(pdf_path)
                        content_input = "".join(page.extract_text() for page in reader.pages)
                        is_url_content = True
                        scene_name_base = Path(pdf_path).stem
                    except Exception as e:
                        await send_error(websocket, f"Failed to process PDF: {e}")
                        continue
                elif topic:
                    content_input = topic
                    scene_name_base = topic
                else:
                    await send_error(websocket, "A topic or PDF file is required.")
                    continue

                await full_animation_pipeline(
                    websocket,
                    content_input=content_input,
                    is_url_content=is_url_content,
                    quality=data.get("quality", "low_quality"),
                    voice=data.get("voice", "achernar"),
                    theme=data.get("theme", "default"),
                    scene_name=scene_name_base.replace(" ", "")
                )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    finally:
        manager.disconnect(websocket)

async def full_animation_pipeline(websocket: WebSocket, content_input: str, is_url_content: bool, quality: str, voice: str, theme: str, scene_name: str):
    try:
        logger.info(f"PIPELINE: Starting for: '{scene_name}'")
        
        ai_content = await one_shot_generation_agent(content_input, websocket, theme, is_url_content)
        if not ai_content:
            return

        narration_text = ai_content["narration"]
        script_content = ai_content["script"]
        image_prompts = ai_content.get("image_prompts", [])
        
        await send_progress(websocket, "AI Result", "Processing generated content...", script=script_content, narration=narration_text)

        if not tts_service: raise Exception("TTS Service not configured.")
        tts_response = await tts_service.generate_speech(TTSRequest(text=narration_text, voice=voice))
        
        final_script = LAYOUT_MANAGER_CODE + "\n" + script_content
        
        if image_prompts and image_service:
            await send_progress(websocket, "Image Gen", f"Generating {len(image_prompts)} image(s)...")
            generated_images_info = []
            for img_prompt in image_prompts:
                try:
                    placeholder = img_prompt["placeholder_id"]
                    description = img_prompt["description"]
                    image_path = await image_service.generate_image(description)
                    final_script = final_script.replace(placeholder, image_path)
                    generated_images_info.append({
                        "path": f"/images/{Path(image_path).name}",
                        "description": description
                    })
                except ImageGenerationError as e:
                    await send_progress(websocket, "Image Gen", f"Skipping image due to error: {e}", status="error")
            
            if generated_images_info:
                await send_progress(websocket, "Image Gen", "Image generation complete.", image_components=generated_images_info)
                logger.info("PIPELINE: Image generation and script injection complete.")
        
        script_path = TEMP_DIR / f"{scene_name}_script.py"
        script_path.write_text(final_script)

        max_render_attempts = 3
        for attempt in range(max_render_attempts):
            try:
                await send_progress(websocket, "Manim", f"Rendering (Attempt {attempt + 1}/{max_render_attempts})...")
                video_path_no_audio = await run_manim_websockets(websocket, str(script_path), scene_name, quality)
                await send_progress(websocket, "Manim", "Rendering successful!")
                
                final_video_path = await combine_audio_video(video_path_no_audio, tts_response.audio_path, OUTPUT_DIR / f"{scene_name}_final.mp4")
                logger.info(f"PIPELINE: Final video created at: {final_video_path}")
                
                await manager.send_json(websocket, {"status": "completed", "output_file": f"/output/{Path(final_video_path).name}"})
                logger.info("PIPELINE: Completed successfully.")
                return
            except ManimRenderingError as e:
                logger.error(f"PIPELINE: Manim rendering failed on attempt {attempt + 1}. Error:\n{e.error_log}")
                if attempt >= max_render_attempts - 1:
                    raise e
                final_script = await debug_manim_script(final_script, e.error_log, websocket)
                script_path.write_text(final_script)
                await send_progress(websocket, "Script Debug", "Applied fix to script.", script=final_script)
        
        raise Exception("PIPELINE: Failed to render video after all attempts.")

    except Exception as e:
        logger.error(f"PIPELINE: A critical error occurred: {e}", exc_info=True)
        await send_error(websocket, f"A critical error occurred in the pipeline: {e}")

async def run_manim_websockets(websocket: WebSocket, script_path: str, scene_name: str, quality: str) -> str:
    logger.info(f"MANIM: Starting render for {script_path}")
    
    video_filename = f"{Path(script_path).stem}.mp4"
    output_path = str(TEMP_DIR / video_filename)

    quality_flags = {"low_quality": "-ql", "medium_quality": "-qm", "high_quality": "-qh", "production_quality": "-qk"}
    cmd = [
        "manim", "render",
        quality_flags.get(quality, "-ql"),
        script_path,
        scene_name,
        "--output_file", output_path
    ]
    
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    
    async def stream_logs(stream, log_prefix, capture_list):
        while True:
            line = await stream.readline()
            if not line: break
            message = line.decode().strip()
            capture_list.append(message)
            logger.info(f"MANIM LOG ({log_prefix}): {message}")
            if "%" in message or "File ready" in message:
                 await send_progress(websocket, f"Manim {log_prefix}", message)

    stdout_capture, stderr_capture = [], []
    await asyncio.gather(
        stream_logs(process.stdout, "stdout", stdout_capture),
        stream_logs(process.stderr, "stderr", stderr_capture)
    )
    await process.wait()
    logger.info(f"MANIM: Process finished with exit code {process.returncode}")

    if process.returncode != 0:
        raise ManimRenderingError("Manim rendering failed", "\n".join(stderr_capture))

    if not Path(output_path).exists():
        raise FileNotFoundError(f"Manim did not produce the expected output file at {output_path}")
    
    logger.info(f"MANIM: Found output file: {output_path}")
    return output_path

async def combine_audio_video(video_path: str, audio_path: str, output_path: Path) -> str:
    logger.info(f"FFMPEG: Combining {video_path} and {audio_path}")
    cmd = ["ffmpeg", "-i", video_path, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-shortest", "-y", str(output_path)]
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_message = stderr.decode()
        logger.error(f"FFMPEG: Failed with error: {error_message}")
        raise Exception(f"FFmpeg failed: {error_message}")
    
    logger.info(f"FFMPEG: Successfully created {output_path}")
    return str(output_path)
