import os
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

load_dotenv()

class ShelfConfig(BaseModel):
    openrouter_api_key: str = Field(
        ...,
        description="OpenRouter API key (REQUIRED)"
    )

    mistral_api_key: str = Field(
        default="",
        description="Mistral API key (optional)"
    )

    datalab_api_key: str = Field(
        default="",
        description="DataLab API key (optional)"
    )

    deepseek_api_key: str = Field(
        default="",
        description="DeepSeek API key (optional)"
    )

    deepinfra_api_key: str = Field(
        default="",
        description="DeepInfra API key (optional)"
    )

    vision_model_primary: str = Field(
        default="",
        description="Primary vision model (fast, cheap)"
    )

    book_storage_root: Path = Field(
        default=Path.home() / "Documents" / "book_scans",
        description="Root directory for book storage"
    )

    @field_validator('openrouter_api_key')
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not v or v.strip() == '':
            raise ValueError(
                "OPENROUTER_API_KEY is required. "
                "Get your key at: https://openrouter.ai/keys"
            )
        return v.strip()

    @field_validator('book_storage_root')
    @classmethod
    def validate_storage_root(cls, v: Path) -> Path:
        return Path(v).expanduser().resolve()

    model_config = {
        "frozen": True,
        "validate_assignment": True
    }


def _load_config() -> ShelfConfig:
    return ShelfConfig(
        openrouter_api_key=(os.getenv('OPENROUTER_API_KEY', '')),
        mistral_api_key=os.getenv('MISTRAL_API_KEY', ''),
        datalab_api_key=os.getenv('DATALAB_API_KEY', ''),
        deepseek_api_key=os.getenv('DEEPSEEK_API_KEY', ''),
        deepinfra_api_key=os.getenv('DEEPINFRA_API_KEY', ''),
        vision_model_primary=os.getenv('VISION_MODEL_PRIMARY', ''),
        book_storage_root=Path(os.getenv('BOOK_STORAGE_ROOT', '~/Documents/book_scans')),
    )

Config = _load_config()
