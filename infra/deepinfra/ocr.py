"""
DeepInfra OCR provider (OlmOCR).

Cost tracking: DeepInfra returns estimated_cost in response.usage.model_extra.
Typical costs for olmOCR-2-7B-1025 (as of 2025-01):
- Input tokens: ~$0.08/M tokens
- Output tokens: ~$0.24/M tokens
- Vision processing: Adds to input token count based on image size

Example costs per ToC page (1-2K tokens):
- Small page (500-1000 chars): $0.0002-0.0005
- Medium page (1000-2000 chars): $0.0005-0.001
- Large page (2000-3000 chars): $0.001-0.002

For 10-page ToC: ~$0.005-0.02 total OCR cost.
"""

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

    def extract_text(self, image: Image.Image, prompt: str = None) -> tuple[str, dict, float]:
        """
        Extract text from image using OlmOCR.

        Args:
            image: PIL Image to OCR
            prompt: Optional prompt (default: "Free OCR")

        Returns:
            Tuple of (text, usage_dict, cost_usd)
            - text: Extracted text string
            - usage_dict: Token usage (prompt_tokens, completion_tokens, total_tokens)
            - cost_usd: Estimated cost in USD from DeepInfra
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

            text = response.choices[0].message.content

            # Extract usage and cost from response
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }

            # DeepInfra provides estimated_cost in model_extra
            cost = 0.0
            if response.usage and hasattr(response.usage, 'model_extra'):
                cost = response.usage.model_extra.get('estimated_cost', 0.0)

            return text, usage, cost

        except Exception as e:
            raise DeepInfraOCRError(f"OlmOCR failed: {e}") from e

    def _image_to_base64(self, image: Image.Image) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")
