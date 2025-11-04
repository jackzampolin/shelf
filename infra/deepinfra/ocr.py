"""DeepInfra OCR provider (OlmOCR)."""

import io
import base64
from PIL import Image
from dotenv import load_dotenv

from .client import DeepInfraClient

load_dotenv()


class DeepInfraOCRError(Exception):
    pass


class OlmOCRProvider:
    def __init__(self, api_key: str = None):
        try:
            self.client = DeepInfraClient(api_key=api_key)
        except Exception as e:
            raise DeepInfraOCRError(f"Failed to initialize DeepInfra client: {e}")

        self.model = "allenai/olmOCR-2-7B-1025"
        self.max_dimension = 2048

    def extract_text(self, image: Image.Image, prompt: str = None) -> str:
        """
        Extract text from image using OlmOCR.

        Args:
            image: PIL Image to OCR
            prompt: Optional prompt (default: "Free OCR")

        Returns:
            Extracted text as string
        """
        try:
            if image.width > self.max_dimension or image.height > self.max_dimension:
                scale = self.max_dimension / max(image.width, image.height)
                new_width = int(image.width * scale)
                new_height = int(image.height * scale)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            image_base64 = self._image_to_base64(image)

            if not prompt:
                prompt = "Free OCR"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ]

            response = self.client.chat_completion(
                model=self.model,
                messages=messages,
                max_tokens=4096,
            )

            if not response.choices or len(response.choices) == 0:
                raise DeepInfraOCRError("No response from OlmOCR")

            return response.choices[0].message.content

        except Exception as e:
            raise DeepInfraOCRError(f"OlmOCR failed: {e}") from e

    def _image_to_base64(self, image: Image.Image) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")
