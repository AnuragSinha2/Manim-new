#!/usr/bin/env python3
"""
Example script to demonstrate how to use the Manim API.
"""
import requests
import json
import sys
import os
from pathlib import Path

API_URL = "http://localhost:8000"

def run_command(command, quality="medium_quality", args=None):
    """Run a Manim command via the API."""
    if args is None:
        args = []
        
    payload = {
        "command": command,
        "quality": quality,
        "args": args
    }
    
    response = requests.post(f"{API_URL}/run-command", json=payload)
    return response.json()

def upload_file(file_path, scene_name=None, quality="medium_quality", args=None):
    """Upload a Python file and run it with Manim."""
    files = {'file': open(file_path, 'rb')}
    
    data = {'quality': quality}
    if scene_name:
        data['scene_name'] = scene_name
    if args:
        data['args'] = args
    
    response = requests.post(f"{API_URL}/run-python-file", files=files, data=data)
    return response.json()

def list_job_files(job_id):
    """List files generated for a specific job."""
    response = requests.get(f"{API_URL}/jobs/{job_id}/files")
    return response.json()

def download_file(job_id, file_name, output_dir="."):
    """Download a specific file from a job."""
    response = requests.get(f"{API_URL}/jobs/{job_id}/files/{file_name}", stream=True)
    
    if response.status_code == 200:
        output_path = Path(output_dir) / file_name
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return str(output_path)
    else:
        print(f"Error downloading file: {response.status_code}")
        return None

def main():
    # Example 1: Run a command
    print("Example 1: Running a Manim command")
    result = run_command("temp/example.py SquareToCircle", quality="low_quality")
    print(json.dumps(result, indent=2))
    
    if result.get("status") == "success":
        job_id = result["job_id"]
        
        # List the files for this job
        print("\nFiles generated:")
        files = list_job_files(job_id)
        print(json.dumps(files, indent=2))
        
        # Download the first file
        if files.get("files") and len(files["files"]) > 0:
            file_name = files["files"][0]
            print(f"\nDownloading {file_name}...")
            path = download_file(job_id, file_name, "output")
            print(f"File downloaded to {path}")
    
    # Example 2: Upload and run a file
    print("\nExample 2: Uploading a file")
    file_path = "temp/example.py"
    
    if os.path.exists(file_path):
        result = upload_file(file_path, scene_name="CreateCircle", quality="low_quality")
        print(json.dumps(result, indent=2))
    else:
        print(f"File {file_path} not found")

if __name__ == "__main__":
    main() 