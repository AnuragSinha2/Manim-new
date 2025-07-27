# app/tts_service.py

import asyncio
import json
import os
import tempfile
import wave
import subprocess
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import google.generativeai as genai
import librosa
import numpy as np
from pydantic import BaseModel

class TTSRequest(BaseModel):
    text: str
    voice: str = "Puck"
    speed: float = 1.0
    scene_duration: Optional[float] = None
    animation_markers: Optional[List[Dict]] = None

class TTSResponse(BaseModel):
    audio_path: str
    duration: float
    sync_data: Optional[Dict] = None

class GeminiTTSService:
    def __init__(self, api_key: str):
        """Initialize the Gemini TTS service with API key."""
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash-preview-tts')
        self.output_dir = Path("/manim/tts_output")
        self.output_dir.mkdir(exist_ok=True)
        
    async def generate_speech(self, request: TTSRequest) -> TTSResponse:
        """Generate speech using Gemini 2.5 Flash TTS with Puck voice."""
        try:
            # Prepare the TTS generation config
            generation_config = {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": request.voice
                        }
                    }
                }
            }
            
            # Add speed control if specified
            if request.speed != 1.0:
                generation_config["speech_config"]["voice_config"]["speed"] = request.speed
            
            # Generate speech
            response = await self._generate_with_retry(request.text, generation_config)
            
            # Save audio to file
            audio_path = self.output_dir / f"tts_{hash(request.text)}.wav"
            await self._save_audio(response, audio_path)
            
            # Get audio duration
            duration = self._get_audio_duration(audio_path)
            
            # Generate sync data if animation markers provided
            sync_data = None
            if request.animation_markers and request.scene_duration:
                sync_data = await self._generate_sync_data(
                    audio_path, duration, request.animation_markers, request.scene_duration
                )
            
            return TTSResponse(
                audio_path=str(audio_path),
                duration=duration,
                sync_data=sync_data
            )
            
        except Exception as e:
            raise Exception(f"TTS generation failed: {str(e)}")
    
    async def _generate_with_retry(self, text: str, config: Dict, max_retries: int = 3) -> any:
        """Generate speech with retry mechanism."""
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(
                    [{"text": text}],
                    generation_config=config,
                )
                return response
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    async def _save_audio(self, response: any, audio_path: Path):
        """Save audio response to WAV file."""
        # Extract audio data from response
        if hasattr(response, 'candidates') and response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data.mime_type.startswith('audio/'):
                    audio_data = part.inline_data.data
                    
                    # Save as temporary PCM file first
                    with tempfile.NamedTemporaryFile(suffix='.pcm', delete=False) as temp_file:
                        temp_file.write(audio_data)
                        temp_pcm_path = temp_file.name
                    
                    # Convert PCM to WAV using ffmpeg
                    subprocess.run([
                        'ffmpeg', '-f', 's16le', '-ar', '24000', '-ac', '1',
                        '-i', temp_pcm_path, '-y', str(audio_path)
                    ], check=True, capture_output=True)
                    
                    # Cleanup temporary file
                    os.unlink(temp_pcm_path)
                    break
    
    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get duration of audio file in seconds."""
        try:
            with wave.open(str(audio_path), 'rb') as audio_file:
                frames = audio_file.getnframes()
                sample_rate = audio_file.getframerate()
                return frames / sample_rate
        except:
            # Fallback using librosa
            y, sr = librosa.load(str(audio_path))
            return len(y) / sr
    
    async def _generate_sync_data(
        self, 
        audio_path: Path, 
        audio_duration: float, 
        animation_markers: List[Dict], 
        scene_duration: float
    ) -> Dict:
        """Generate synchronization data for animation and voice."""
        
        # Load audio for analysis
        y, sr = librosa.load(str(audio_path))
        
        # Extract speech features for timing
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)
        
        # Calculate timing adjustments
        speed_factor = scene_duration / audio_duration if audio_duration > 0 else 1.0
        
        sync_data = {
            "audio_duration": audio_duration,
            "scene_duration": scene_duration,
            "speed_factor": speed_factor,
            "onset_times": onset_times.tolist(),
            "animation_sync": []
        }
        
        # Map animation markers to audio segments
        for i, marker in enumerate(animation_markers):
            marker_time = marker.get('time', i * (scene_duration / len(animation_markers)))
            audio_time = marker_time / speed_factor
            
            # Find closest onset
            closest_onset = min(onset_times, key=lambda x: abs(x - audio_time)) if len(onset_times) > 0 else audio_time
            
            sync_data["animation_sync"].append({
                "marker_name": marker.get('name', f'marker_{i}'),
                "animation_time": marker_time,
                "audio_time": closest_onset,
                "sync_offset": closest_onset - audio_time
            })
        
        return sync_data

class AnimationVoiceSync:
    """Handles synchronization between Manim animations and TTS audio."""
    
    @staticmethod
    def generate_synced_manim_script(
        original_script: str, 
        tts_response: TTSResponse,
        sync_method: str = "stretch"
    ) -> str:
        """Generate a Manim script that's synchronized with the TTS audio."""
        
        if not tts_response.sync_data:
            return original_script
        
        sync_data = tts_response.sync_data
        speed_factor = sync_data["speed_factor"]
        
        # Add audio playback and timing adjustments to the script
        sync_additions = f"""
# Auto-generated TTS synchronization code
import pygame
from manim import *

class TTSSyncedScene(Scene):
    def setup_audio(self):
        pygame.mixer.init()
        self.audio_file = "{tts_response.audio_path}"
        self.audio_duration = {tts_response.duration}
        self.speed_factor = {speed_factor}
    
    def play_synced_audio(self):
        pygame.mixer.music.load(self.audio_file)
        pygame.mixer.music.play()
    
    def wait_synced(self, duration):
        # Adjust wait times based on audio sync
        adjusted_duration = duration * self.speed_factor
        self.wait(adjusted_duration)
"""
        
        # Insert sync code into original script
        lines = original_script.split('\n')
        
        # Find the class definition and add sync methods
        for i, line in enumerate(lines):
            if 'class' in line and 'Scene' in line:
                # Insert sync methods after class definition
                indent = '    '
                sync_methods = [
                    f'{indent}def setup_audio(self):',
                    f'{indent}    pygame.mixer.init()',
                    f'{indent}    self.audio_file = "{tts_response.audio_path}"',
                    f'{indent}    self.audio_duration = {tts_response.duration}',
                    f'{indent}    self.speed_factor = {speed_factor}',
                    f'{indent}',
                    f'{indent}def play_synced_audio(self):',
                    f'{indent}    pygame.mixer.music.load(self.audio_file)',
                    f'{indent}    pygame.mixer.music.play()',
                    f'{indent}',
                    f'{indent}def wait_synced(self, duration):',
                    f'{indent}    adjusted_duration = duration * self.speed_factor',
                    f'{indent}    self.wait(adjusted_duration)',
                    f'{indent}'
                ]
                
                lines[i+1:i+1] = sync_methods
                break
        
        # Replace wait() calls with wait_synced() and add audio setup
        synced_script = '\n'.join(lines)
        
        # Add audio playback at the beginning of construct method
        synced_script = synced_script.replace(
            'def construct(self):',
            '''def construct(self):
        self.setup_audio()
        self.play_synced_audio()'''
        )
        
        # Replace wait calls with synced versions
        synced_script = synced_script.replace('self.wait(', 'self.wait_synced(')
        
        return synced_script

# Enhanced FastAPI endpoints for TTS integration