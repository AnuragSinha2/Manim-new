# app/image_service.py
import asyncio
from pathlib import Path
from PIL import Image
import logging
import os
import google.generativeai as genai

logger = logging.getLogger(__name__)

# This service now uses the Gemini Imagen 4 model to generate images.
async def generate_image(prompt: str, output_path: Path, transparent_background: bool):
    """
    Generates an image using Imagen 4 based on a prompt.
    """
    logger.info(f"Generating Imagen 4 image for prompt: '{prompt}' at {output_path}")
    
    try:
        # Configure the model for image generation
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

        # The image generation API in the GenerativeModel is synchronous,
        # so we run it in a separate thread to avoid blocking the event loop.
        result = await asyncio.to_thread(
            client.images.generate,
            model="models/imagen-4.0-generate-preview-06-06",
            prompt=prompt,
            config=dict(
                number_of_images=1,
                output_mime_type="image/png" if transparent_background else "image/jpeg",
                person_generation="ALLOW_ADULT",
                aspect_ratio="1:1",
            ),
        )

        if not result.generated_images:
            raise Exception("No image candidates were returned by the API.")

        # Extract the first image from the response
        generated_image = result.generated_images[0]
        
        # The image data is in generated_image.image.getvalue()
        image_data = generated_image.image.getvalue()
        
        # Ensure the output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save the image data to the specified path
        with open(output_path, "wb") as f:
            f.write(image_data)
        
        logger.info(f"Successfully saved Imagen 4 image to {output_path}")

    except Exception as e:
        logger.error(f"Failed to generate or save image for prompt '{prompt}': {e}", exc_info=True)
        # As a fallback, create a placeholder error image
        create_error_image(prompt, output_path)
        raise  # Re-raise the exception to be handled by the calling agent


def create_error_image(prompt: str, output_path: Path):
    """Creates a placeholder image to indicate an error during generation."""
    try:
        img = Image.new('RGB', (512, 512), color='red')
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), "ERROR: Image generation failed.", fill=(255, 255, 255))
        draw.text((10, 30), prompt[:50], fill=(255, 255, 255))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, 'PNG')
        logger.info(f"Saved error placeholder image to {output_path}")
    except Exception as e:
        logger.error(f"Failed to create even the error placeholder image: {e}")
