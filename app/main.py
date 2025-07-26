import os
import json
import stat
import datetime
import mimetypes
import subprocess
import uuid
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from fastapi import FastAPI, HTTPException, Query, Path as PathParam, Body, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi_mcp import FastApiMCP
import google.generativeai as genai
import asyncio

# Configure the Gemini API key
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(title="Manim Project API", description="API for managing and creating Manim animations with project support.")

PROJECTS_BASE_DIR = "/manim/projects"

# Mount static files directory for a frontend
app.mount("/ui", StaticFiles(directory="/manim/frontend"), name="ui")
app.mount("/projects", StaticFiles(directory=PROJECTS_BASE_DIR), name="projects")

# --- Project Management ---

class Project(BaseModel):
    project_name: str = Field(..., description="Name of the project")

@app.post("/projects", status_code=201)
def create_project(project: Project):
    """Creates a new project with a standard directory structure."""
    project_path = os.path.join(PROJECTS_BASE_DIR, project.project_name)
    if os.path.exists(project_path):
        raise HTTPException(status_code=409, detail="Project already exists")
    
    try:
        os.makedirs(os.path.join(project_path, "animations"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "media"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "output"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "temp"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "uploads"), exist_ok=True)
        return {"status": "success", "message": f"Project '{project.project_name}' created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)}")

@app.get("/projects")
def list_projects():
    """Lists all available projects."""
    if not os.path.exists(PROJECTS_BASE_DIR):
        return []
    return [d for d in os.listdir(PROJECTS_BASE_DIR) if os.path.isdir(os.path.join(PROJECTS_BASE_DIR, d))]

@app.delete("/projects/{project_name}")
def delete_project(project_name: str):
    """Deletes a project and all its contents."""
    project_path = os.path.join(PROJECTS_BASE_DIR, project_name)
    if not os.path.exists(project_path):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        shutil.rmtree(project_path)
        return {"status": "success", "message": f"Project '{project_name}' deleted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {str(e)}")

# --- File Management (Project-Aware) ---

def get_project_path(project_name: str):
    """Helper to get a project's path and check if it exists."""
    project_path = os.path.join(PROJECTS_BASE_DIR, project_name)
    if not os.path.exists(project_path):
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found.")
    return project_path

@app.get("/projects/{project_name}/files")
def list_project_files(project_name: str, path: str = Query(".")):
    """Lists files in a specific directory within a project."""
    project_path = get_project_path(project_name)
    target_path = os.path.normpath(os.path.join(project_path, path))

    if not os.path.exists(target_path) or not os.path.isdir(target_path):
        raise HTTPException(status_code=404, detail="Directory not found.")
        
    if not target_path.startswith(project_path):
        raise HTTPException(status_code=403, detail="Access denied.")

    return os.listdir(target_path)

# ... other file management endpoints to be updated ...

# --- Gemini Manim Script Generation (Project-Aware) ---
class ManimScriptRequest(BaseModel):
    prompt: str = Field(..., description="Natural language prompt describing the animation")
    file_name: Optional[str] = Field(None, description="Optional file name for the generated script (e.g., 'animation.py')")

@app.post("/projects/{project_name}/generate-manim-script")
def generate_manim_script(project_name: str, request: ManimScriptRequest):
    """
    Generate a Manim animation script from a natural language prompt using Gemini.
    """
    project_path = get_project_path(project_name)
    animations_dir = os.path.join(project_path, "animations")

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured")

    try:
        # ... (Gemini generation logic remains the same)
        model = genai.GenerativeModel('gemini-2.5-pro')
        prompt_parts = [
            "You are an expert in Manim, the mathematical animation engine for Python.",
            "Your task is to generate a Python script for a Manim animation based on the user's description.",
            "The script must be robust and avoid common errors.",
            "Follow these guidelines strictly:",
            "1.  **Imports:** Start with `from manim import *`.",
            "2.  **Class Definition:** Define a single scene class that inherits from `manim.Scene`.",
            "3.  **`construct` Method:** All animation logic must be inside the `construct(self)` method.",
            "4.  **Simplicity:** Use simple and standard Manim objects and animations (e.g., `Create`, `Write`, `Transform`, `FadeIn`, `FadeOut`). Avoid complex or experimental features.",
            "5.  **Compatibility:** The code should be compatible with the latest version of Manim Community Edition.",
            "6.  **Self-Contained:** The script must be a single block of code that can be saved directly to a Python file and run without modifications.",
            "7.  **No External Dependencies:** Do not use any libraries other than Manim.",
            "8.  **Text:** Use `Text` for rendering text. For mathematical formulas, use `MathTex`.",
            "9.  **Positioning:** Use relative positioning (e.g., `.next_to()`, `.shift()`) to avoid objects going off-screen.",
            "10. **Wait Times:** Include `self.wait()` calls after animations to control the pacing.",
            "\n---\n",
            f"User's Description: '{request.prompt}'",
            "\n---\n",
            "Now, generate the Manim script.",
        ]
        response = model.generate_content(prompt_parts)
        script_content = response.text.strip()
        if script_content.startswith("```python"):
            script_content = script_content[9:]
        if script_content.endswith("```"):
            script_content = script_content[:-3]

        file_name = request.file_name or f"generated_{uuid.uuid4().hex[:8]}.py"
        file_path = os.path.join(animations_dir, file_name)
        
        with open(file_path, "w") as f:
            f.write(script_content)

        return {
            "status": "success",
            "message": "Manim script generated successfully",
            "file_path": file_path,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Manim script: {str(e)}")


# --- Manim Execution with Real-time Updates ---

class ManimRunRequest(BaseModel):
    file_path: str
    scene_name: str
    quality: str = "medium_quality"

@app.websocket("/ws/run-manim/{project_name}")
async def run_manim_ws(websocket: WebSocket, project_name: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            request = ManimRunRequest.parse_raw(data)
            
            project_path = get_project_path(project_name)
            script_path = os.path.normpath(os.path.join(project_path, request.file_path))

            if not script_path.startswith(project_path) or not os.path.exists(script_path):
                await websocket.send_text(json.dumps({"status": "error", "message": "Invalid file path."}))
                continue

            output_dir = os.path.join(project_path, "output", str(uuid.uuid4()))
            os.makedirs(output_dir, exist_ok=True)

            cmd = [
                "python3", "-m", "manim",
                "-ql" if request.quality == "low_quality" else "-qm",
                "--output_file", output_dir,
                script_path, request.scene_name
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Stream stdout and stderr
            async def stream_output(stream, stream_name):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    await websocket.send_text(json.dumps({"stream": stream_name, "data": line.decode()}))

            await asyncio.gather(
                stream_output(process.stdout, "stdout"),
                stream_output(process.stderr, "stderr")
            )

            await process.wait()
            
            # Find the output file
            output_file = None
            if os.path.exists(output_dir):
                for f in os.listdir(output_dir):
                    if f.endswith('.mp4'):
                        output_file = os.path.join(output_dir, f)
                        break

            await websocket.send_text(json.dumps({
                "status": "completed", 
                "output_file": output_file
            }))

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        await websocket.send_text(json.dumps({"status": "error", "message": str(e)}))
        await websocket.close()

# --- Root and MCP ---
@app.get("/")
def read_root():
    return {"message": "Welcome to the Manim Project API. Visit /ui/index.html for the web interface."}

@app.websocket("/ws/generate-full-animation")
async def generate_full_animation_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_text()
        request = json.loads(data)
        topic = request.get("topic")

        if not topic:
            await websocket.send_text(json.dumps({"status": "error", "message": "Topic is required."}))
            return

        project_name = "default"
        project_path = os.path.join(PROJECTS_BASE_DIR, project_name)
        os.makedirs(project_path, exist_ok=True)
        for sub_dir in ["animations", "media", "output", "temp", "uploads"]:
            os.makedirs(os.path.join(project_path, sub_dir), exist_ok=True)

        await websocket.send_text(json.dumps({"status": "progress", "stage": "AI Script Generation", "message": "Generating educational script for the topic..."}))

        # Step 1: Generate educational script
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured")

        model = genai.GenerativeModel('gemini-2.5-pro')
        script_prompt = [
            "You are an educational scriptwriter. Create a concise, clear, and engaging script to explain the following topic. The script will be used for a short animated video.",
            f"Topic: '{topic}'",
            "The script should be broken down into logical scenes or steps. Keep it simple and focused on the core concepts.",
            "Output only the raw text of the script, without any titles or formatting."
        ]
        response = model.generate_content(script_prompt)
        educational_script = response.text.strip()

        await websocket.send_text(json.dumps({"status": "progress", "stage": "AI Manim Code Generation", "message": "Generating Manim code from the script..."}))

        # Step 2: Generate Manim code from the script
        manim_prompt = [
            "You are a Manim expert. Convert the following educational script into a single Python script for a Manim animation.",
            "The script should visually represent the explanation. Use simple and clear animations.",
            "The output should be a single block of Python code, ready to be saved to a .py file.",
            "Ensure the scene class is named 'GeneratedScene'.",
            "Here is the script:",
            educational_script
        ]
        response = model.generate_content(manim_prompt)
        manim_code = response.text.strip()
        if manim_code.startswith("```python"):
            manim_code = manim_code[9:]
        if manim_code.endswith("```"):
            manim_code = manim_code[:-3]

        # Step 3: Save the Manim code
        script_file_name = f"generated_{uuid.uuid4().hex[:8]}.py"
        script_path = os.path.join(project_path, "animations", script_file_name)
        with open(script_path, "w") as f:
            f.write(manim_code)

        await websocket.send_text(json.dumps({"status": "progress", "stage": "TTS Generation", "message": "Generating audio for the script..."}))

        # Step 4: Generate TTS audio using Gemini TTS API
        await websocket.send_text(json.dumps({"status": "progress", "stage": "TTS Generation", "message": "Generating audio using Gemini TTS..."}))
        try:
            audio_file_name = f"generated_{uuid.uuid4().hex[:8]}.mp3"
            audio_path = os.path.join(project_path, "output", audio_file_name)

            # Use Gemini TTS model for audio output with correct parameters
            tts_model = genai.GenerativeModel('gemini-2.5-flash-exp')
            tts_response = tts_model.generate_content(
                educational_script,
                response_mime_types=["audio/mpeg"]
            )
            
            # Save the audio content to file
            if tts_response.candidates and len(tts_response.candidates) > 0:
                candidate = tts_response.candidates[0]
                if candidate.content and len(candidate.content.parts) > 0:
                    audio_data = candidate.content.parts[0].inline_data.data
                    with open(audio_path, "wb") as audio_file:
                        audio_file.write(audio_data)
                    await websocket.send_text(json.dumps({"status": "progress", "stage": "TTS Generation", "message": "Audio saved successfully using Gemini TTS."}))
                else:
                    raise Exception("No audio data in response")
            else:
                raise Exception("No candidates in TTS response")
                
        except Exception as e:
            await websocket.send_text(json.dumps({"status": "error", "stage": "TTS Generation", "message": f"Gemini TTS failed: {str(e)}. Continuing without audio..."}))
            # Continue without audio instead of failing completely
            audio_path = None

        await websocket.send_text(json.dumps({"status": "progress", "stage": "Animation Execution", "message": "Running Manim to create the video..."}))

        # Step 5: Execute the animation
        output_dir = os.path.join(project_path, "output", str(uuid.uuid4()))
        os.makedirs(output_dir, exist_ok=True)
        video_path = os.path.join(output_dir, "animation.mp4")

        cmd = [
            "python3", "-m", "manim",
            "-qm",  # Medium quality
            "--output_file", video_path,
            script_path, "GeneratedScene"
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        async def stream_output(stream, stream_name):
            while True:
                line = await stream.readline()
                if not line:
                    break
                await websocket.send_text(json.dumps({"status": "progress", "stage": "Manim Log", "message": line.decode()}))

        await asyncio.gather(
            stream_output(process.stdout, "stdout"),
            stream_output(process.stderr, "stderr")
        )

        await process.wait()

        # Step 6: Merge audio and video (only if audio was generated successfully)
        final_video_path = video_path  # Default to video-only
        
        if audio_path and os.path.exists(audio_path):
            await websocket.send_text(json.dumps({"status": "progress", "stage": "Audio/Video Merge", "message": "Merging audio and video..."}))
            
            final_video_path = os.path.join(output_dir, "final_animation.mp4")
            merge_cmd = [
                "ffmpeg",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-strict", "experimental",
                "-y",  # Overwrite output files without asking
                final_video_path
            ]
            
            try:
                merge_process = await asyncio.create_subprocess_exec(
                    *merge_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                await merge_process.wait()
                
                if merge_process.returncode != 0:
                    # If merge fails, use video-only
                    final_video_path = video_path
                    await websocket.send_text(json.dumps({"status": "progress", "stage": "Audio/Video Merge", "message": "Audio merge failed, using video-only output."}))
            except Exception as e:
                # If merge fails, use video-only
                final_video_path = video_path
                await websocket.send_text(json.dumps({"status": "progress", "stage": "Audio/Video Merge", "message": f"Audio merge failed: {str(e)}, using video-only output."}))

        # Step 7: Find and return the output file
        output_file = None
        if os.path.exists(final_video_path):
            relative_path = os.path.relpath(final_video_path, PROJECTS_BASE_DIR)
            output_file = f"/projects/{relative_path}"
        
        if output_file:
            await websocket.send_text(json.dumps({
                "status": "completed",
                "output_file": output_file
            }))
        else:
            await websocket.send_text(json.dumps({
                "status": "error",
                "message": "Animation file not found after execution."
            }))

    except Exception as e:
        await websocket.send_text(json.dumps({"status": "error", "message": str(e)}))
    finally:
        await websocket.close()


mcp = FastApiMCP(app)
mcp.mount()