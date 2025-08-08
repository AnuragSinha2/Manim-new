# app/tts_service.py

import os
import uuid
import wave
from pydantic import BaseModel
from typing import List, Dict
from google import genai
from google.genai import types
import librosa
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# --- Data Models ---
class TTSRequest(BaseModel):
    text: str
    voice: str = "achernar"

class TTSResponse(BaseModel):
    audio_path: str
    duration: float

# --- TTS Service ---
class GeminiTTSService:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiTTSService.")
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash-preview-tts"
        self.output_dir = Path("/manim/tts_output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_speech(self, request: TTSRequest) -> TTSResponse:
        logger.info(f"Generating speech with {self.model_name} for voice: {request.voice}")

        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=request.text)],
            ),
        ]
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=request.voice
                    )
                )
            ),
        )

        output_filename = self.output_dir / f"{uuid.uuid4()}.wav"
        audio_data = b""

        try:
            stream = self.client.models.generate_content_stream(
                model=self.model_name,
                contents=contents,
                config=generate_content_config,
            )

            for chunk in stream:
                if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                    part = chunk.candidates[0].content.parts[0]
                    if part.inline_data and part.inline_data.data:
                        audio_data += part.inline_data.data
            
            if not audio_data:
                raise ValueError("No audio data received from the API.")

            with wave.open(str(output_filename), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(audio_data)

        except Exception as e:
            logger.error(f"Gemini TTS API call failed: {e}", exc_info=True)
            raise

        logger.info(f"Audio content written to file: {output_filename}")

        try:
            duration = librosa.get_duration(path=str(output_filename))
        except Exception as e:
            logger.error(f"Failed to get duration from audio file {output_filename}: {e}")
            duration = 10.0  # Fallback duration

        return TTSResponse(
            audio_path=str(output_filename),
            duration=duration
        )
