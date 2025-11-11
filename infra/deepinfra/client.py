import os
from typing import Any, Dict, List
from dotenv import load_dotenv

load_dotenv()

class DeepInfraError(Exception):
    pass


class DeepInfraClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("DEEPINFRA_API_KEY")
        if not self.api_key:
            raise DeepInfraError("DEEPINFRA_API_KEY not found")

        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.deepinfra.com/v1/openai",
            )
        except ImportError as e:
            raise DeepInfraError(f"openai package not installed: {e}")

    def chat_completion(self, model: str, messages: List[Dict[str, Any]], **kwargs) -> Any:
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
            return response
        except Exception as e:
            raise DeepInfraError(f"Chat completion failed: {e}") from e
