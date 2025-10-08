"""
LLM-powered book discovery from PDF files.

Scans directories for PDFs and extracts metadata using vision models.
"""

import sys
import json
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from pdf2image import convert_from_path
from io import BytesIO

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from platform.llm_client import LLMClient
from platform.pricing import CostCalculator

from platform.config import Config


def extract_book_metadata(pdf_path: Path) -> Optional[Dict[str, Any]]:
    """
    Extract book metadata from PDF using vision model.

    Converts first 3 pages to images and sends to Claude Sonnet 4.5
    to extract title, author, year, publisher, and ISBN.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dict with extracted metadata, or None if extraction fails
    """
    print(f"Extracting metadata from: {pdf_path.name}")

    try:
        # Convert first 3 pages to images
        images = convert_from_path(pdf_path, first_page=1, last_page=3, dpi=150)

        # Convert images to base64
        image_data = []
        for img in images:
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            image_data.append(img_b64)

        # Build prompt for LLM
        prompt = """Analyze these pages from a book and extract the following metadata:

1. **Title**: Full book title
2. **Author**: Author name(s)
3. **Year**: Publication year (integer)
4. **Publisher**: Publisher name
5. **ISBN**: ISBN-10 or ISBN-13 if visible

Return your response as a JSON object with these exact keys:
```json
{
  "title": "Book Title",
  "author": "Author Name",
  "year": 2023,
  "publisher": "Publisher Name",
  "isbn": "1234567890"
}
```

If any field is not found, use null. Be precise and extract exactly what you see."""

        # Build message with images (OpenAI format for OpenRouter compatibility)
        content = [{"type": "text", "text": prompt}]
        for img_b64 in image_data:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_b64}"
                }
            })

        # Call OpenRouter API
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {Config.OPEN_ROUTER_API_KEY}",
                "HTTP-Referer": Config.OPEN_ROUTER_SITE_URL,
                "X-Title": Config.OPEN_ROUTER_SITE_NAME,
                "Content-Type": "application/json"
            },
            json={
                "model": Config.STRUCTURE_MODEL,  # Use Claude Sonnet 4.5
                "messages": [
                    {
                        "role": "user",
                        "content": content
                    }
                ]
            },
            timeout=60
        )

        response.raise_for_status()
        result = response.json()

        # Track cost using dynamic pricing
        usage = result.get('usage', {})
        if usage:
            calc = CostCalculator()
            cost = calc.calculate_cost(
                Config.STRUCTURE_MODEL,
                usage.get('prompt_tokens', 0),
                usage.get('completion_tokens', 0),
                num_images=len(image_data)
            )
            print(f"  💰 LLM cost: ${cost:.4f}")

        # Extract and parse response
        assistant_message = result["choices"][0]["message"]["content"]

        # Try to extract JSON from response
        metadata = _extract_json_from_response(assistant_message)

        if metadata:
            print(f"  ✓ Extracted: {metadata.get('title')} by {metadata.get('author')}")
            return metadata
        else:
            print(f"  ✗ Failed to parse metadata")
            return None

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return None


def discover_books_in_directory(directory: Path) -> List[Dict[str, Any]]:
    """
    Scan directory for PDF files and extract metadata.

    Args:
        directory: Path to scan

    Returns:
        List of dicts with 'pdf_path' and 'metadata' keys
    """
    directory = Path(directory).expanduser()

    if not directory.exists():
        print(f"Directory not found: {directory}")
        return []

    # Find all PDFs
    pdf_files = list(directory.glob("*.pdf"))
    pdf_files.extend(directory.glob("**/*.pdf"))  # Recursive
    pdf_files = list(set(pdf_files))  # Deduplicate

    print(f"Found {len(pdf_files)} PDF(s) in {directory}")

    results = []
    for pdf_path in pdf_files:
        metadata = extract_book_metadata(pdf_path)
        if metadata:
            results.append({
                "pdf_path": pdf_path,
                "metadata": metadata
            })

    return results


def _extract_json_from_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON object from LLM response.

    Handles various response formats (code blocks, plain JSON, etc.)

    Args:
        text: LLM response text

    Returns:
        Parsed JSON dict or None
    """
    # Try to find JSON in code blocks
    import re

    # Look for ```json ... ``` or ``` ... ```
    code_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    matches = re.findall(code_block_pattern, text, re.DOTALL)

    if matches:
        try:
            return json.loads(matches[0])
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, text, re.DOTALL)

    for match in matches:
        try:
            data = json.loads(match)
            # Validate it has expected keys
            if "title" in data or "author" in data:
                return data
        except json.JSONDecodeError:
            continue

    return None
