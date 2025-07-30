# app/tts_service.py

import asyncio
import json
import os
import tempfile
import wave
import subprocess
import shutil
import ast
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import google.generativeai as genai
import librosa
import numpy as np
from pydantic import BaseModel

class TTSRequest(BaseModel):
    text: str
    script: str
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
                    audio_path, duration, request.animation_markers, request.scene_duration, request.script
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

                    # Pipe the audio data directly to ffmpeg's stdin
                    process = subprocess.run([
                        'ffmpeg', '-f', 's16le', '-ar', '24000', '-ac', '1',
                        '-i', '-', '-y', str(audio_path)
                    ], input=audio_data, check=True, capture_output=True)
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
        scene_duration: float,
        script_content: str
    ) -> Dict:
        """Generate synchronization data for animation and voice."""

        true_video_duration = AnimationVoiceSync._get_true_video_duration(script_content)

        # Load audio for analysis
        y, sr = librosa.load(str(audio_path))

        # Extract speech features for timing
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)

        # Calculate timing adjustments
        speed_factor = audio_duration / true_video_duration if true_video_duration > 0 else 1.0

        sync_data = {
            "audio_duration": audio_duration,
            "scene_duration": true_video_duration,
            "speed_factor": speed_factor,
            "onset_times": onset_times.tolist(),
            "animation_sync": []
        }

        # Map animation markers to audio segments
        for i, marker in enumerate(animation_markers):
            marker_time = marker.get('time', i * (true_video_duration / len(animation_markers)))
            audio_time = marker_time * speed_factor

            # Find closest onset
            closest_onset = min(onset_times, key=lambda x: abs(x - audio_time)) if len(onset_times) > 0 else audio_time

            sync_data["animation_sync"].append({
                "marker_name": marker.get('name', f'marker_{i}'),
                "animation_time": marker_time,
                "audio_time": closest_onset,
                "sync_offset": closest_onset - audio_time
            })

        return sync_data

class ScriptTransformer(ast.NodeTransformer):
    def __init__(self, speed_factor):
        self.speed_factor = speed_factor

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'wait':
                if node.args:
                    duration_node = node.args[0]
                    if isinstance(duration_node, ast.Constant):
                        duration_node.value *= self.speed_factor
                    elif isinstance(duration_node, ast.Num):
                        duration_node.n *= self.speed_factor
                else:
                    node.args.append(ast.Constant(value=1.0 * self.speed_factor))
                return node
            elif node.func.attr == 'play':
                has_run_time = False
                for keyword in node.keywords:
                    if keyword.arg == 'run_time':
                        has_run_time = True
                        if isinstance(keyword.value, ast.Constant):
                            keyword.value.value *= self.speed_factor
                        elif isinstance(keyword.value, ast.Num):
                            keyword.value.n *= self.speed_factor
                        break
                if not has_run_time:
                    node.keywords.append(ast.keyword(arg='run_time', value=ast.Constant(value=1.0 * self.speed_factor)))
                return node
        return node

class AnimationVoiceSync:
    """Handles synchronization between Manim animations and TTS audio."""

    @staticmethod
    def _get_true_video_duration(script_content: str) -> float:
        """
        Analyzes a Manim script using an AST to determine its true total duration.
        """
        total_duration = 0.0
        try:
            tree = ast.parse(script_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'wait':
                        if node.args:
                            duration_node = node.args[0]
                            if isinstance(duration_node, ast.Constant):
                                total_duration += duration_node.value
                            elif isinstance(duration_node, ast.Num):
                                total_duration += duration_node.n
                        else:
                            total_duration += 1.0
                    elif node.func.attr == 'play':
                        run_time = 1.0
                        for keyword in node.keywords:
                            if keyword.arg == 'run_time':
                                if isinstance(keyword.value, ast.Constant):
                                    run_time = keyword.value.value
                                elif isinstance(keyword.value, ast.Num):
                                    run_time = keyword.value.n
                                break
                        total_duration += run_time
        except Exception as e:
            print(f"Could not parse script to get duration: {e}")
            return len(script_content.splitlines()) * 0.5
        return total_duration

    @staticmethod
    def generate_synced_manim_script(
        original_script: str,
        tts_response: TTSResponse,
        sync_method: str = "stretch"
    ) -> str:
        """Generate a Manim script that's synchronized with the TTS audio."""

        if not tts_response.sync_data:
            return original_script

        speed_factor = tts_response.sync_data["speed_factor"]

        tree = ast.parse(original_script)
        transformer = ScriptTransformer(speed_factor=speed_factor)
        new_tree = transformer.visit(tree)

        # Add audio playback at the beginning of construct method
        for node in ast.walk(new_tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == 'construct':
                        # Add audio setup and playback
                        setup_audio_call = ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='setup_audio', ctx=ast.Load()), args=[], keywords=[]))
                        play_audio_call = ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='play_synced_audio', ctx=ast.Load()), args=[], keywords=[]))
                        item.body.insert(0, play_audio_call)
                        item.body.insert(0, setup_audio_call)

                        # Add final wait
                        new_duration = AnimationVoiceSync._get_true_video_duration(ast.unparse(new_tree))
                        if tts_response.duration > new_duration:
                            padding = tts_response.duration - new_duration
                            final_wait = ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='wait', ctx=ast.Load()), args=[ast.Constant(value=padding)], keywords=[]))
                            item.body.append(final_wait)
                        break

        # Add the helper methods to the class
        for node in ast.walk(new_tree):
            if isinstance(node, ast.ClassDef):
                # setup_audio
                setup_audio_def = ast.FunctionDef(
                    name='setup_audio',
                    args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='self')], defaults=[], kwonlyargs=[], kw_defaults=[]),
                    body=[
                        ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Attribute(value=ast.Name(id='pygame', ctx=ast.Load()), attr='mixer', ctx=ast.Load()), attr='init', ctx=ast.Load()), args=[], keywords=[])),
                        ast.Assign(targets=[ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='audio_file', ctx=ast.Store())], value=ast.Constant(value=tts_response.audio_path)),
                        ast.Assign(targets=[ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='audio_duration', ctx=ast.Store())], value=ast.Constant(value=tts_response.duration)),
                        ast.Assign(targets=[ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='speed_factor', ctx=ast.Store())], value=ast.Constant(value=speed_factor)),
                    ],
                    decorator_list=[]
                )
                # play_synced_audio
                play_audio_def = ast.FunctionDef(
                    name='play_synced_audio',
                    args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='self')], defaults=[], kwonlyargs=[], kw_defaults=[]),
                    body=[
                        ast.Expr(value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Attribute(
                                    value=ast.Attribute(
                                        value=ast.Name(id='pygame', ctx=ast.Load()),
                                        attr='mixer',
                                        ctx=ast.Load()
                                    ),
                                    attr='music',
                                    ctx=ast.Load()
                                ),
                                attr='load',
                                ctx=ast.Load()
                            ),
                            args=[ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='audio_file', ctx=ast.Load())],
                            keywords=[]
                        )),
                        ast.Expr(value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Attribute(
                                    value=ast.Attribute(
                                        value=ast.Name(id='pygame', ctx=ast.Load()),
                                        attr='mixer',
                                        ctx=ast.Load()
                                    ),
                                    attr='music',
                                    ctx=ast.Load()
                                ),
                                attr='play',
                                ctx=ast.Load()
                            ),
                            args=[],
                            keywords=[]
                        )),
                    ],
                    decorator_list=[]
                )
                node.body.insert(0, play_audio_def)
                node.body.insert(0, setup_audio_def)
                break

        # Add `import pygame`
        new_tree.body.insert(0, ast.Import(names=[ast.alias(name='pygame')]))

        ast.fix_missing_locations(new_tree)

        return ast.unparse(new_tree)

# Enhanced FastAPI endpoints for TTS integration
