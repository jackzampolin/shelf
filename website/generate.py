#!/usr/bin/env python3
"""Generate shelf.dev website from code context.

This script extracts metadata from the codebase and uses Claude to generate
the website HTML. Run on every push to main via GitHub Actions.

Usage:
    python website/generate.py              # Generate to website/dist/
    python website/generate.py --preview    # Generate and open in browser
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from anthropic import Anthropic

from infra.pipeline.registry import get_all_stage_metadata


# Fixed content that doesn't change
FIXED_CONTENT = {
    "project_name": "shelf",
    "tagline": "Scans to structured text",
    "github_repo": "jackzampolin/shelf",
    "domain": "shelf.dev",

    # Project background - the "why" behind shelf
    "project_background": """Not every book is available as an audiobook. Military history, academic texts, out-of-print nonfiction—if you want to listen to them, you have to make them yourself.

Raw OCR gets you text, but text mixed with garbage—page numbers read aloud, running headers interrupting every page, image captions scattered through the text, footnote numbers with no footnotes. The result is technically an audiobook, but not one you'd want to listen to.

Getting something close to the quality of a professionally produced Audible audiobook—with no user discernible issues—turns out to be an unsolved problem. Those audiobooks have human editors. Getting that quality with software alone, with little to no human intervention, is the challenge shelf is designed to solve.""",

    # Pipeline explanation - what shelf does with a scan
    "pipeline_explanation": """Once you have a book scan (either from a sheet-fed scanner after cutting the spine, or a non-destructive overhead scanner), shelf runs it through a multi-stage AI pipeline. Each stage builds on the last: multiple OCR providers extract the text, LLMs classify and label the structure (body text vs headers vs footnotes vs page numbers), the table of contents is extracted and linked to actual pages, and finally clean ePub files are produced—text that flows when read aloud.""",
}

# The prompt template for Claude
PROMPT_TEMPLATE = '''You are generating the landing page HTML for shelf.dev.

## Fixed Content (use exactly as provided)
- Project name: {project_name}
- Tagline: {tagline}

## Project Background (use this prose in the hero section)
{project_background}

## Pipeline Explanation (use this to introduce the pipeline section)
{pipeline_explanation}

## Pipeline Stages (extracted from code - show all stages with their phases)
{stages_json}

## Project Stats
- Lines of Python: {loc}
- Number of stages: {num_stages}

## Design Requirements
- Dark theme with #0a0a0a background
- Use Inter font for text, JetBrains Mono for code
- Blue accent color (#3b82f6)
- Mobile responsive
- Self-contained HTML (all CSS inline, no external files except fonts)

## Required Sections
1. **Navigation** - Just the logo "shelf" on the left. No other nav links or buttons.
2. **Hero** - The tagline "{tagline}" as the main heading, then the project_background prose below it. NO buttons (no "Get Started", no "Learn More", no GitHub links).
3. **Pipeline** - First show the pipeline_explanation paragraph, then the visual flow of all {num_stages} stages. For each stage show the icon, name, description, and list its phases with their descriptions.
4. **Footer** - Simple footer with just "shelf" and the current year. No external links.

## What NOT to include
- No GitHub links or buttons anywhere
- No "Open Source" badges or messaging
- No "Get Started" or "Learn More" buttons
- No Quick Start / installation instructions
- No feature cards section (the pipeline IS the features)

## Output
Generate ONLY valid HTML. No markdown, no explanation, no code fences.
Start with <!DOCTYPE html> and end with </html>.
'''


def get_github_stats(repo: str) -> dict:
    """Fetch GitHub stats via gh CLI."""
    try:
        # Get repo info
        result = subprocess.run(
            ["gh", "repo", "view", repo, "--json", "stargazerCount,issues"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {
                "stars": data.get("stargazerCount", 0),
                "open_issues": data.get("issues", {}).get("totalCount", 0)
            }
    except Exception:
        pass
    return {"stars": "N/A", "open_issues": "N/A"}


def count_lines_of_code() -> int:
    """Count lines of Python code in the project."""
    project_root = Path(__file__).parent.parent
    total = 0
    for py_file in project_root.rglob("*.py"):
        # Skip venv, cache, etc.
        if any(part.startswith(".") or part in ("venv", "__pycache__", "dist", "build")
               for part in py_file.parts):
            continue
        try:
            total += len(py_file.read_text().splitlines())
        except Exception:
            pass
    return total


def extract_context() -> dict:
    """Extract all context from the codebase."""
    stages = get_all_stage_metadata()
    github_stats = get_github_stats(FIXED_CONTENT["github_repo"])
    loc = count_lines_of_code()

    return {
        **FIXED_CONTENT,
        "stages": stages,
        "stages_json": json.dumps(stages, indent=2),
        "num_stages": len(stages),
        "loc": f"{loc:,}",
        **github_stats,
    }


def generate_html(context: dict, max_retries: int = 3) -> str:
    """Call Claude to generate the website HTML."""
    client = Anthropic()
    prompt = PROMPT_TEMPLATE.format(**context)

    for attempt in range(max_retries):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}]
        )

        html = response.content[0].text.strip()

        # Validate it looks like HTML
        if html.startswith("<!DOCTYPE html") and html.endswith("</html>"):
            return html

        # Try to extract HTML if wrapped in code fences
        if "```html" in html:
            html = html.split("```html")[1].split("```")[0].strip()
            if html.startswith("<!DOCTYPE html") and html.endswith("</html>"):
                return html

        print(f"Attempt {attempt + 1}: Invalid HTML output, retrying...")

    raise ValueError("Failed to generate valid HTML after retries")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate shelf.dev website")
    parser.add_argument("--preview", action="store_true", help="Open in browser after generation")
    parser.add_argument("--output", default="website/dist/index.html", help="Output path")
    args = parser.parse_args()

    print("Extracting context from codebase...")
    context = extract_context()
    print(f"  - {context['num_stages']} pipeline stages")
    print(f"  - {context['loc']} lines of Python")
    print(f"  - {context['stars']} GitHub stars")

    print("\nGenerating HTML with Claude...")
    html = generate_html(context)

    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write output
    output_path.write_text(html)
    print(f"\nGenerated: {output_path}")

    # Also copy CNAME if it exists
    cname_src = Path("website/CNAME")
    if cname_src.exists():
        cname_dst = output_path.parent / "CNAME"
        cname_dst.write_text(cname_src.read_text())
        print(f"Copied: {cname_dst}")

    if args.preview:
        import webbrowser
        webbrowser.open(f"file://{output_path.absolute()}")
        print("Opened in browser")


if __name__ == "__main__":
    main()
