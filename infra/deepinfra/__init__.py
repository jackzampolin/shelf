"""DeepInfra API client - generic OpenAI-compatible endpoint wrapper."""

from .client import DeepInfraClient, DeepInfraError

__all__ = [
    "DeepInfraClient",
    "DeepInfraError",
]
