# app/image_service.py

import logging
import uuid
from pathlib import Path
import asyncio
import vertexai
from vertexai.preview.vision_models import ImageGenerationModel

logger = logging.getLogger(__name__)

class ImageGenerationError(Exception):
    pass

class ImageService:
    def __init__(self, project_id: str, location: str):
        if not project_id or not location:
            raise ValueError("Google Cloud Project ID and Location are required for Vertex AI.")
        
        # Initialize Vertex AI
        try:
            vertexai.init(project=project_id, location=location)
            self.model = ImageGenerationModel.from_pretrained("imagen-4.0-generate-preview-06-06")
            logger.info("Vertex AI ImageService initialized successfully with Imagen.")
        except Exception as e:
            logger.error(f"Failed to initialize Vertex AI: {e}")
            raise ImageGenerationError(f"Vertex AI initialization failed: {e}")

        self.output_dir = Path("/manim/images")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _generate_sync(self, prompt: str):
        """Synchronous wrapper for the Vertex AI image generation call."""
        try:
            images = self.model.generate_images(
                prompt=prompt,
                number_of_images=1,
                aspect_ratio="1:1",
            )
            return images
        except Exception as e:
            logger.error(f"Underlying Vertex AI API call failed: {e}")
            raise ImageGenerationError(f"API call failed: {e}")

    async def generate_image(self, prompt: str) -> str:
        """
        Generates an image from a text prompt using Vertex AI Imagen and saves it.
        """
        logger.info(f"Generating image with Vertex AI Imagen for prompt: '{prompt}'")
        
        try:
            # Run the synchronous SDK call in a separate thread
            images = await asyncio.to_thread(self._generate_sync, prompt)

            if not images:
                raise ImageGenerationError("API response did not contain image data.")

            output_filename = self.output_dir / f"{uuid.uuid4()}.png"
            
            # Save the first image
            images[0].save(location=str(output_filename), include_generation_parameters=False)
            
            logger.info(f"Successfully saved image to {output_filename}")
            return str(output_filename)

        except Exception as e:
            logger.error(f"Image generation failed for prompt '{prompt}': {e}")
            raise ImageGenerationError(f"Failed to generate image: {e}")