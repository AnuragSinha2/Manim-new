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
from google.cloud import aiplatform
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from .tts_service import GeminiTTSService, TTSRequest, AnimationVoiceSync
from .image_service import generate_image

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
    # Configure Vertex AI
    PROJECT_ID = "sheshya-cloud"
    LOCATION_ID = "asia-east1"
    vertexai.init(project=PROJECT_ID, location=LOCATION_ID)
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
async def imagen_agent(narration: str, websocket: WebSocket) -> list[dict]:
    await send_progress(websocket, "AI Agent: Visual Director", "Identifying key visual moments for image generation...")
    
    prompt = f"""
You are a Visual Director for an educational video. Your task is to analyze the following narration script and identify 3-4 key concepts or objects that would be best illustrated with a custom-generated image.

**Narration Script:**
---
{narration}
---

**Instructions:**
1.  Read the script carefully and pinpoint the most visually impactful moments.
2.  For each moment, create a concise, descriptive prompt for an AI image generator (like Imagen or DALL-E 3). The prompt should be detailed enough to generate a clear and relevant image.
3.  Decide if the image should have a transparent background (to be used as an overlay on other content) or a scenic background (to be used as a full-frame shot).
4.  Provide a short, unique, snake_case `id` for each image.
5.  Your final output must be a single, raw JSON object with one key: "image_requests". This key should contain a list of the image descriptions.

**Example JSON Output:**
{{
  "image_requests": [
    {{
      "id": "mitochondria_closeup",
      "description": "A detailed, scientific illustration of a mitochondrion, showing the inner and outer membranes, cristae, and matrix. Labeled for clarity. Vibrant colors, 4k.",
      "background": "transparent"
    }},
    {{
      "id": "atp_energy_cycle",
      "description": "A dynamic, glowing visualization of the ATP energy cycle, with ADP turning into ATP, releasing a burst of light. Abstract, conceptual.",
      "background": "scenic"
    }}
  ]
}}
"""
    if not script_model:
        raise Exception("Image component generation model is not configured.")

    try:
        response = await script_model.generate_content_async(prompt)
        raw_response_text = response.text
        logger.info(f"Raw Imagen agent response: {raw_response_text}")
        
        content = ultimate_json_parser(raw_response_text)
        image_requests = content.get("image_requests", [])

        if not image_requests:
            await send_progress(websocket, "AI Agent: Visual Director", "No suitable moments for image generation were found.")
            return []

        await send_progress(websocket, "AI Agent: Visual Director", f"Identified {len(image_requests)} images to generate. Starting generation...")

        image_generation_tasks = []
        generated_image_info = []
        
        # Use a sub-directory for this generation task
        generation_id = str(abs(hash(narration)))
        image_output_dir = TEMP_DIR / "images" / generation_id
        image_output_dir.mkdir(parents=True, exist_ok=True)

        for req in image_requests:
            image_id = req.get("id", "unnamed_image")
            description = req.get("description", "no description")
            bg_type = req.get("background", "scenic")
            is_transparent = (bg_type == "transparent")
            
            output_path = image_output_dir / f"{image_id}.png"
            
            task = generate_image(description, output_path, is_transparent)
            image_generation_tasks.append(task)
            
            generated_image_info.append({
                "id": image_id,
                "description": description,
                "path": f"/temp/images/{generation_id}/{image_id}.png"
            })

        await asyncio.gather(*image_generation_tasks)
        
        await send_progress(websocket, "Image Generation", "All image components generated successfully.")
        await manager.send_json(websocket, {"image_components": generated_image_info})
        
        return generated_image_info

    except Exception as e:
        logger.error(f"Error in imagen_agent: {e}", exc_info=True)
        await send_progress(websocket, "Error", f"Failed to generate image components: {e}", status="error")
        return []

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
    prompt = f'You are a professional scriptwriter for educational videos. Your task is to write a clear, concise, and engaging narration script for an animation explaining the topic: "{topic}". Determine an appropriate length for the script based on the complexity of the topic, aiming for a comprehensive yet brief explanation. Focus on clarity and a logical flow. Do not include any other text, formatting, or JSON structure. Your output should be only the raw text of the narration.'
    if not script_model: raise Exception("Script generation model is not configured.")
    
    try:
        # Add a timeout to the API call
        response = await asyncio.wait_for(
            script_model.generate_content_async(prompt),
            timeout=90.0
        )
        narration_text = response.text.strip()
        await send_progress(websocket, "AI Agent: Narrator", "Narration script generated successfully.")
        await manager.send_json(websocket, {"narration": narration_text})
        return narration_text
    except asyncio.TimeoutError:
        raise Exception("The narration generation timed out. The AI service may be slow or unavailable.")
    except Exception as e:
        logger.error(f"An error occurred in narration_agent: {e}", exc_info=True)
        raise e

async def manim_scripting_agent(topic: str, narration: str, websocket: WebSocket, model: str = "gemini", image_components: list[dict] = None, error_message: str = None, original_script: str = None) -> str:
    scene_name = topic.replace(" ", "").capitalize()
    
    # --- Gold Standard Example for Few-Shot Prompting ---
    few_shot_example = """
**Example of a GOOD, BUG-FREE Manim Script:**
```python
from manim import *

class SolarSystem(Scene):
    def construct(self):
        # Setup objects
        sun = Circle(radius=1, color=YELLOW, fill_opacity=1).to_edge(LEFT, buff=1)
        sun_label = Text("Sun").next_to(sun, DOWN)
        
        planet = Circle(radius=0.2, color=BLUE, fill_opacity=1).next_to(sun, RIGHT, buff=2)
        planet_label = Text("Planet").next_to(planet, DOWN)
        
        # Initial animation
        self.play(Create(sun), Write(sun_label))
        self.wait(1)
        self.play(FadeIn(planet, shift=RIGHT), Write(planet_label))
        
        # Clear previous elements before showing new ones
        self.play(*[FadeOut(mob) for mob in self.mobjects])
        self.wait(0.5)
        
        # Second part of animation
        final_text = Text("Animations complete!").scale(1.5)
        self.play(Write(final_text))
        self.wait(2)
```
"""

    if error_message and original_script:
        await send_progress(websocket, "AI Agent: Manim Scripter", "Sending script back to the AI for debugging...")
        prompt = f"""You are an expert Manim scriptwriter and debugger for Manim v0.19.0. Your primary goal is to fix the provided script. The script you wrote previously has failed with an error. You must fix it, ensuring the corrected code is complete, runnable, and still provides a clear visual explanation for the narration.

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
**Here is an example of a perfect, bug-free Manim script to guide you:**
{few_shot_example}

**Instructions:**
1.  Analyze the error message and the faulty script to identify the root cause of the problem.
2.  Provide a corrected, complete, and runnable version of the script.
3.  The final output must be a single, raw JSON object with one key: "script". Do not include any other text or markdown.
"""
        model_to_use = debugging_model
        if not model_to_use: raise Exception("Debugging model is not configured.")
    else:
        await send_progress(websocket, "AI Agent: Manim Scripter", "Generating Manim script based on narration and images...")
        
        image_assets_prompt_section = ""
        if image_components:
            image_assets_prompt_section += "\n**Available Image Assets:**\nYou have access to the following pre-generated images. Use them with `ImageMobject(\"path/to/image.png\")` where they best fit the narration. Remember to scale them appropriately (e.g., `.scale(0.5)`) and position them so they don't overlap with other elements.\n"
            for img in image_components:
                image_assets_prompt_section += f"""
- Image ID: `{img['id']}`
  - Path: `{img['path']}`
  - Description: "{img['description']}"
"""
        
        prompt = f"""You are an expert Manim scriptwriter and visual educator for Manim v0.19.0. Your primary goal is to create a clear, bug-free animation script that visually explains the provided narration.

**The final output must be a single, raw JSON object containing one key: "script".**

**Narration to Animate:**
---
{narration}
---
{image_assets_prompt_section}
**CRITICAL Rules for Manim Scripting:**
1.  **Class Naming:** The Scene class MUST be named `{scene_name}`.
2.  **No Overlapping:** Elements must NOT overlap. Before adding new, unrelated elements, you MUST clear the screen using `self.play(*[FadeOut(mob) for mob in self.mobjects])`.
3.  **Stay On Screen:** All text and animations must be clearly visible within the frame. Use `.scale()` to make objects smaller if they are too large. `ImageMobject` almost always needs scaling.
4.  **Intelligent Positioning:** Use relative positioning like `.to_edge()`, `.next_to()`, and `.shift()`. AVOID hardcoding coordinates like `(x, y, z)`.
5.  **Color Usage:** Use ONLY standard Manim colors in all capitals (e.g., `BLUE`, `RED`, `GREEN`) or hex codes (e.g., `'#FFFFFF'`). Do NOT use lowercase color names (e.g., `'blue'`).
6.  **Forbidden Techniques:** Do NOT use `SVGMobject`. Do NOT use rate functions (e.g., `rate_func=...`).
7.  **Self-Contained:** The script must be a single, complete piece of code that can be run directly.

**Here is an example of a perfect, bug-free Manim script. Follow its structure and style:**
{few_shot_example}

**Instructions:**
1.  First, create a step-by-step visual storyboard plan as comments in your head.
2.  Translate that plan into a complete and runnable Manim script that follows all the rules above.
3.  Wrap the final script in a JSON object like `{{"script": "..."}}`.
"""
        if model == "claude":
            model_to_use = GenerativeModel("claude-3-5-sonnet@20240620")
        else:
            model_to_use = script_model
        if not model_to_use: raise Exception("Script generation model is not configured.")

    if model == "claude":
        response = await asyncio.to_thread(
            model_to_use.generate_content,
            [prompt]
        )
    else:
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
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        stdout_str = stdout.decode().strip()
        stderr_str = stderr.decode().strip()

        if stdout_str:
            logger.info(f"Manim stdout:\n{stdout_str}")
            await send_progress(websocket, "Manim Log", stdout_str)
        if stderr_str:
            logger.error(f"Manim stderr:\n{stderr_str}")
            await send_progress(websocket, "Manim Log", stderr_str)

        # More robust error checking: A real failure will have a non-zero exit code
        # AND a "Traceback" in the error log. Warnings alone won't trigger the debug loop.
        is_real_error = "Traceback (most recent call last):" in stderr_str

        if process.returncode != 0 and is_real_error:
            error_message = stderr_str or "Manim rendering failed with an unknown error."
            raise Exception(error_message)

        video_path_match = re.search(r"File saved at '(.*?)'", stdout_str)
        if not video_path_match:
            # If the primary output log doesn't mention a file, check stderr as a fallback.
            video_path_match_err = re.search(r"File saved at '(.*?)'", stderr_str)
            if not video_path_match_err:
                 raise FileNotFoundError("Could not find the Manim output file path in the logs.")
            video_path = video_path_match_err.group(1)
        else:
            video_path = video_path_match.group(1)
        
        # CRITICAL: Verify the file actually exists
        if not Path(video_path).is_file():
            raise FileNotFoundError(f"Manim reported saving a file at '{video_path}', but it was not found. This indicates a silent failure.")
            
        return video_path

    except Exception as e:
        logger.error(f"An unexpected error occurred during Manim execution: {e}", exc_info=True)
        raise e

async def combine_audio_video(video_path: str, audio_path: str, output_path: Path) -> str:
    logger.info(f"Attempting to combine video '{video_path}' and audio '{audio_path}'")
    
    # Verify files exist before calling ffmpeg
    if not Path(video_path).is_file():
        raise FileNotFoundError(f"FFmpeg error: Video file not found at {video_path}")
    if not Path(audio_path).is_file():
        raise FileNotFoundError(f"FFmpeg error: Audio file not found at {audio_path}")

    cmd = ["ffmpeg", "-i", video_path, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-shortest", "-y", str(output_path)]
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise Exception(f"FFmpeg failed: {stderr.decode()}")
    logger.info(f"FFmpeg successfully created '{output_path}'")
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
                model = data.get("model", "gemini")
                generation_task = asyncio.create_task(
                    run_generation_pipeline(websocket, topic, quality, voice, model)
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

async def static_analysis_agent(script_content: str, websocket: WebSocket) -> Optional[str]:
    """
    Performs static analysis on the Manim script to catch common errors
    before rendering.
    """
    await send_progress(websocket, "Pre-flight Check", "Analyzing script for common errors...")
    
    errors = []
    
    # Basic Python syntax check
    try:
        ast.parse(script_content)
    except (SyntaxError, IndentationError) as e:
        errors.append(f"Invalid Python syntax: {e}")
        # No need to check further if basic syntax is wrong
        return "\n".join(errors)

    # Manim-specific checks using regex
    # 1. Check for lowercase colors (that aren't hex codes)
    color_pattern = r"""color\s*=\s*['"](?!#)([a-z]+)['"]"""
    lowercase_colors = re.findall(color_pattern, script_content)
    if lowercase_colors:
        errors.append(f"Found potential lowercase color names: {list(set(lowercase_colors))}. Use uppercase constants like BLUE or hex codes like '#FFFFFF'.")

    # 2. Check for forbidden SVGMobject
    if "SVGMobject" in script_content:
        errors.append("Forbidden class `SVGMobject` was used. Please use `ImageMobject` for images or standard Manim shapes.")
        
    # 3. Check for hardcoded positioning (a bit trickier, but we can look for common patterns)
    hardcoded_pos_pattern = r"\\.move_to\\(\\s*\[\\s*\\d"
    if re.search(hardcoded_pos_pattern, script_content):
        errors.append("Potential hardcoded position found with `.move_to()`. Prefer relative positioning like `.next_to()` or `.to_edge()`.")

    if errors:
        await send_progress(websocket, "Pre-flight Check", f"Found {len(errors)} potential issues.")
        return "\n".join(errors)
    
    await send_progress(websocket, "Pre-flight Check", "Script analysis passed.")
    return None

async def run_generation_pipeline(websocket: WebSocket, topic: str, quality: str, voice: str, model: str):
    try:
        scene_name = topic.replace(" ", "").capitalize()
        
        # Step 1: Generate narration
        narration_text = await narration_agent(topic, websocket)
        
        # Step 2: Generate image components (DISABLED)
        await send_progress(websocket, "AI Agent: Visual Director", "Image generation is currently disabled by the user.")
        image_components = []
        # image_components = await imagen_agent(narration_text, websocket)
        
        # Step 3: Generate the initial Manim script
        current_script_content = await manim_scripting_agent(topic, narration_text, websocket, model, image_components=image_components)
        
        # Step 4: Generate TTS audio
        if not tts_service: raise Exception("TTS Service is not configured.")
        tts_request = TTSRequest(text=narration_text, voice=voice)
        tts_response = await tts_service.generate_speech(tts_request)
        tts_audio_url = f"/tts_output/{Path(tts_response.audio_path).name}"
        await manager.send_json(websocket, {"tts_audio_url": tts_audio_url})

        video_path_no_audio = None
        max_retries = 5

        for attempt in range(max_retries):
            await send_progress(websocket, "Manim", f"Starting rendering attempt #{attempt + 1}/{max_retries}...")
            
            # Pre-flight static analysis
            static_analysis_errors = await static_analysis_agent(current_script_content, websocket)
            if static_analysis_errors:
                await send_progress(websocket, "Debug Agent", "Static analysis failed. Fixing script...")
                current_script_content = await manim_scripting_agent(
                    topic, narration_text, websocket, model,
                    image_components=image_components, 
                    error_message=f"Static analysis failed with the following issues:\n{static_analysis_errors}", 
                    original_script=current_script_content
                )
                continue # Retry with the fixed script

            try:
                # Apply audio synchronization
                synced_script_content = AnimationVoiceSync.generate_synced_manim_script(current_script_content, tts_response)
                synced_script_path = TEMP_DIR / f"{scene_name}_synced_script_attempt_{attempt + 1}.py"
                synced_script_path.write_text(synced_script_content)
                
                # Attempt to render
                video_path_no_audio = await run_manim_websockets(websocket, str(synced_script_path), scene_name, quality)
                
                # If rendering is successful, break the loop
                await send_progress(websocket, "Manim", "Rendering successful!")
                break

            except Exception as e:
                error_message = str(e)
                await send_progress(websocket, "Manim", f"Rendering attempt #{attempt + 1} failed.")
                
                if attempt == max_retries - 1:
                    await send_progress(websocket, "Error", "All rendering attempts failed.", status="error")
                    raise Exception(f"Exceeded maximum rendering retries. Last error: {error_message}")
                
                await send_progress(websocket, "Debug Agent", "Attempting to fix the script...")
                current_script_content = await manim_scripting_agent(
                    topic, narration_text, websocket, model,
                    image_components=image_components, 
                    error_message=error_message, 
                    original_script=current_script_content
                )

        if not video_path_no_audio:
            raise Exception("Failed to render video after all debugging attempts.")

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
app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")

@app.get("/")
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / 'index.html')