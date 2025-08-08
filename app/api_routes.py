# app/api_routes.py

import os
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from pathlib import Path

router = APIRouter()
BASE_DIR = Path("/manim")
UPLOADS_DIR = BASE_DIR / "uploads"

class FilePath(BaseModel):
    path: str

@router.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serves the main HTML frontend."""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if not frontend_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return HTMLResponse(content=frontend_path.read_text(), status_code=200)

@router.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """Handles PDF file uploads."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")

    file_location = UPLOADS_DIR / file.filename
    try:
        with open(file_location, "wb+") as file_object:
            file_object.write(file.file.read())
        return {"status": "success", "path": str(file_location)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not upload file: {e}")

@router.get("/download-file")
async def download_file(filepath: str):
    """Serves a file for download."""
    file_path = Path(filepath)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path=str(file_path), filename=file_path.name)