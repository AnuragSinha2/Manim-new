# app/agents.py

import logging
import re
import json
import google.generativeai as genai
from fastapi import WebSocket

from ws_utils import send_progress

logger = logging.getLogger(__name__)

# --- AI Model Configuration ---
try:
    generation_model = genai.GenerativeModel('gemini-2.5-pro')
    debug_model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    logger.error(f"Failed to initialize Gemini models: {e}")
    generation_model = None
    debug_model = None

def clean_ai_response(raw_text: str) -> str:
    """
    Finds and extracts the first valid JSON object from a string.
    """
    json_match = re.search(r'```json\s*(\{.*\})\s*```', raw_text, re.DOTALL)
    if json_match:
        return json_match.group(1)
    
    json_match = re.search(r'(\{.*\})', raw_text, re.DOTALL)
    if json_match:
        return json_match.group(1)
        
    raise ValueError("No valid JSON object found in the AI response.")

async def one_shot_generation_agent(content_input: str, websocket: WebSocket, theme: str = "default", is_url_content: bool = False) -> dict | None:
    """
    Generates a full storyboard, narration, and Manim script from a topic or URL content.
    """
    await send_progress(websocket, "AI Storyboard", f"Generating storyboard with '{theme}' theme...")
    
    scene_name = "AnimationScene"
    if not is_url_content:
        scene_name = content_input.replace(" ", "")

    theme_instructions = {
        "dark": "Use a dark background (e.g., `#27272a`) and light-colored text/objects (e.g., `WHITE`, `BLUE_C`).",
        "playful": "Use bright, vibrant colors (e.g., `RED`, `GREEN`, `YELLOW`) and playful animations like `GrowFromCenter`, `SpinIn`.",
        "default": "Use the standard Manim dark background and a balanced color palette."
    }
    
    prompt = f"""
    You are an expert AI director for Manim, the mathematical animation engine.
    Your goal is to generate a complete plan for a short video based on the topic: "{content_input}".

    **Creative Direction**: Create a visually engaging video that is a DYNAMIC MIX of Manim animations and still images. Do not just show a series of static images. Use Manim's animation capabilities to create motion and explain concepts, and use still images to illustrate specific points or add visual variety.

    The visual theme for the animation must be: **{theme}**.
    **Theme instructions**: {theme_instructions.get(theme, theme_instructions['default'])}

    You must return a single, valid JSON object with three keys:
    1.  `"narration"`: A clear, concise narration script for the entire video as a single string.
    2.  `"image_prompts"`: A list of dictionaries for images to be generated. Each must have a `"placeholder_id"` and a `"description"`. If no images, return an empty list.
    3.  `"script"`: A complete, runnable Python script for a single Manim scene named `{scene_name}`.

    **CRITICAL SCRIPT REQUIREMENTS**:
    - **Pacing**: The animation timings (`self.play`, `self.wait`) MUST be paced to match the flow of the narration you write.
    - **Adhere to the Theme**: The script's colors and animation choices must reflect the theme instructions.
    - **NO SVGs**: Do NOT use the `SVGMobject` class. All vector graphics must be requested via `image_prompts` and rendered with `ImageMobject`.
    - **Use `Group` for Images**: When grouping `ImageMobject` objects with other objects, you MUST use `Group`, not `VGroup`.
    - **Image Placeholders**: If you need an image, you MUST use the `ImageMobject` class in your script with the exact `placeholder_id` as the filename.
    - **Use LayoutManager**: The script MUST use the provided `LayoutManager` for all object positioning.
    - **Clearing Screen**: Use `self.play(FadeOut(*layout.get_all_mobjects()))` to clear the screen between major ideas.
    - **Simplicity**: Use simple, common Manim objects and animations. Avoid obscure or complex features.
    - **Variable Names**: Do NOT use file paths as variable names. Use descriptive names like `image1`, `image2`, etc.
    """
    if not generation_model:
        raise Exception("Generation model not configured.")

    try:
        response = await generation_model.generate_content_async(prompt)
        cleaned_text = clean_ai_response(response.text)
        ai_content = json.loads(cleaned_text)

        if not all(k in ai_content for k in ["narration", "script", "image_prompts"]):
            raise ValueError("AI response was missing required keys.")

        await send_progress(websocket, "AI Storyboard", "Full storyboard and script generated.")
        return ai_content
    except Exception as e:
        logger.error(f"AI One-Shot Generation failed: {e}", exc_info=True)
        await send_progress(websocket, "Error", f"AI failed to generate content: {e}", status="error")
        return None

async def debug_manim_script(original_script: str, error_log: str, websocket: WebSocket) -> str:
    """
    Attempts to fix a failing Manim script using an AI model.
    """
    await send_progress(websocket, "AI Debugging", "Analyzing rendering error and attempting to fix script...")
    prompt = f"""
    The following Manim script failed with an error. Analyze the error, fix the script, and learn from the mistake.
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
    if not debug_model:
        raise Exception("Debug model not configured.")
    try:
        response = await debug_model.generate_content_async(prompt)
        cleaned_text = clean_ai_response(response.text)
        script_data = json.loads(cleaned_text)
        await send_progress(websocket, "AI Debugging", "Script fixed. Retrying render.")
        return script_data['script']
    except Exception as e:
        logger.error(f"AI Debugging failed: {e}", exc_info=True)
        raise Exception(f"AI debugger failed: {e}")
