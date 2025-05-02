import os
import subprocess
import shutil
import uuid
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Manim API", description="API for running Manim animations")

# Create directories if they don't exist
os.makedirs("/manim/uploads", exist_ok=True)
os.makedirs("/manim/output", exist_ok=True)
os.makedirs("/manim/temp", exist_ok=True)

# Mount static files directory for video downloads
app.mount("/output", StaticFiles(directory="/manim/output"), name="output")

class ManimRequest(BaseModel):
    command: str
    quality: str = "medium_quality"
    args: Optional[List[str]] = []

@app.get("/")
def read_root():
    return {"message": "Manim API is running"}

@app.post("/run-command")
def run_command(request: ManimRequest):
    """Run a Manim command with the specified options"""
    
    # Generate a unique ID for this job
    job_id = str(uuid.uuid4())
    output_dir = f"/manim/output/{job_id}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Build the command
    cmd = ["python3", "-m", "manim"]
    
    # Add quality flag
    if request.quality == "low_quality":
        cmd.append("-ql")
    elif request.quality == "medium_quality":
        cmd.append("-qm")
    elif request.quality == "high_quality":
        cmd.append("-qh")
    elif request.quality == "production_quality":
        cmd.append("-qk")
    
    # Add output directory
    cmd.extend(["--output_file", output_dir])
    
    # Add the main command
    cmd.append(request.command)
    
    # Add any additional arguments
    if request.args:
        cmd.extend(request.args)
    
    try:
        # Run the command
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True,
            check=True
        )
        
        # List generated files
        files = []
        if os.path.exists(output_dir):
            files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
        
        return {
            "job_id": job_id,
            "status": "success",
            "command": " ".join(cmd),
            "output": result.stdout,
            "files": files,
            "download_urls": [f"/output/{job_id}/{file}" for file in files]
        }
    
    except subprocess.CalledProcessError as e:
        return {
            "job_id": job_id,
            "status": "error",
            "command": " ".join(cmd),
            "error": e.stderr,
            "returncode": e.returncode
        }

@app.post("/run-python-file")
async def run_python_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    quality: str = Form("medium_quality"),
    scene_name: Optional[str] = Form(None),
    args: Optional[str] = Form(None)
):
    """Upload a Python file and run it with Manim"""
    
    # Generate a unique ID for this job
    job_id = str(uuid.uuid4())
    file_path = f"/manim/uploads/{job_id}_{file.filename}"
    output_dir = f"/manim/output/{job_id}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Save the uploaded file
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    # Build the command
    cmd = ["python3", "-m", "manim"]
    
    # Add quality flag
    if quality == "low_quality":
        cmd.append("-ql")
    elif quality == "medium_quality":
        cmd.append("-qm")
    elif quality == "high_quality":
        cmd.append("-qh")
    elif quality == "production_quality":
        cmd.append("-qk")
    
    # Add output directory
    cmd.extend(["--output_file", output_dir])
    
    # Add the file path
    cmd.append(file_path)
    
    # Add scene name if provided
    if scene_name:
        cmd.append(scene_name)
    
    # Add additional arguments if provided
    if args:
        cmd.extend(args.split())
    
    try:
        # Run the command
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True,
            check=True
        )
        
        # List generated files
        files = []
        if os.path.exists(output_dir):
            files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
        
        # Schedule cleanup of the uploaded file
        background_tasks.add_task(os.remove, file_path)
        
        return {
            "job_id": job_id,
            "status": "success",
            "command": " ".join(cmd),
            "output": result.stdout,
            "files": files,
            "download_urls": [f"/output/{job_id}/{file}" for file in files]
        }
    
    except subprocess.CalledProcessError as e:
        # Clean up on error
        background_tasks.add_task(os.remove, file_path)
        
        return {
            "job_id": job_id,
            "status": "error",
            "command": " ".join(cmd),
            "error": e.stderr,
            "returncode": e.returncode
        }

@app.get("/jobs/{job_id}/files")
def list_job_files(job_id: str):
    """List files generated for a specific job"""
    output_dir = f"/manim/output/{job_id}"
    
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Job not found")
    
    files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
    
    return {
        "job_id": job_id,
        "files": files,
        "download_urls": [f"/output/{job_id}/{file}" for file in files]
    }

@app.get("/jobs/{job_id}/files/{file_name}")
def get_job_file(job_id: str, file_name: str):
    """Download a specific file from a job"""
    file_path = f"/manim/output/{job_id}/{file_name}"
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(file_path) 