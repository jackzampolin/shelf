#!/usr/bin/env python3
"""
Stage 4: Deep Structure - Use LLM to semantically structure entire book in one pass.

Approach: Feed complete book to LLM, get back deeply structured JSON with:
- Chapters with true semantic boundaries
- Properly grouped paragraphs (handling cross-page splits)
- Section detection within chapters
- Summaries and context
- Semantic chunks for RAG

Input: corrected/*.json (page-level corrected text)
Output: structured/ (deeply structured chapters and chunks)

Cost: ~$6/book (300K in, 350K out) - worth it for quality over $0.01 hack
"""

import os
import sys
import json
import re
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from pricing import CostCalculator


class DeepBookStructurer:
    """Use LLM to deeply understand and structure entire book in one pass."""

    def __init__(self, book_slug: str, model: str = None, storage_root: Path = None):
        self.book_slug = book_slug
        self.storage_root = storage_root or (Path.home() / "Documents" / "book_scans")
        self.book_dir = self.storage_root / book_slug

        # Directories
        self.corrected_dir = self.book_dir / "corrected"
        self.structured_dir = self.book_dir / "structured"
        self.chapters_dir = self.structured_dir / "chapters"
        self.chunks_dir = self.structured_dir / "chunks"

        # Create output directories
        for d in [self.structured_dir, self.chapters_dir, self.chunks_dir]:
            d.mkdir(exist_ok=True)

        # Load API key
        load_dotenv()
        self.api_key = os.getenv('OPEN_ROUTER_API_KEY') or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("No OpenRouter API key found in environment")

        # Model selection (allow override for cost optimization)
        self.model = model or "anthropic/claude-sonnet-4.5"  # Can use cheaper models

        # Initialize cost calculator with dynamic pricing
        self.cost_calculator = CostCalculator()

        # Stats
        self.stats = {
            "pages_loaded": 0,
            "chapters_detected": 0,
            "paragraphs_created": 0,
            "chunks_created": 0,
            "total_cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0
        }

    def call_llm(self, system_prompt: str, user_prompt: str, temperature=0.0, stream=False):
        """Make API call to OpenRouter with optional streaming."""
        url = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jackzampolin/ar-research",
            "X-Title": "AR Research Deep Book Structuring"
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "stream": stream
        }

        if not stream:
            # Non-streaming (original behavior)
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()

            result = response.json()

            # Extract usage for cost tracking
            usage = result.get('usage', {})
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)

            self.stats['input_tokens'] += prompt_tokens
            self.stats['output_tokens'] += completion_tokens

            # Calculate cost using dynamic pricing from OpenRouter API
            cost = self.cost_calculator.calculate_cost(
                self.model,
                prompt_tokens,
                completion_tokens
            )
            self.stats['total_cost_usd'] += cost

            return result['choices'][0]['message']['content'], usage

        else:
            # Streaming with progress bar
            response = requests.post(url, headers=headers, json=payload, stream=True)
            response.raise_for_status()

            full_content = []
            tokens_received = 0

            print("📊 Streaming response (progress bar shows tokens received):")
            sys.stdout.flush()

            for line in response.iter_lines():
                if not line:
                    continue

                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]  # Remove 'data: ' prefix

                    if data_str == '[DONE]':
                        break

                    try:
                        chunk = json.loads(data_str)
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk['choices'][0].get('delta', {})
                            content = delta.get('content', '')

                            if content:
                                full_content.append(content)
                                tokens_received += 1

                                # Update progress every 100 tokens
                                if tokens_received % 100 == 0:
                                    print(f"\r   Tokens: {tokens_received:,}...", end='', flush=True)
                    except json.JSONDecodeError:
                        continue

            print(f"\r   Tokens: {tokens_received:,} ✓")
            sys.stdout.flush()

            complete_response = ''.join(full_content)

            # Estimate usage (streaming doesn't provide exact counts)
            usage = {
                'prompt_tokens': len(user_prompt.split()) + len(system_prompt.split()),
                'completion_tokens': tokens_received
            }

            self.stats['input_tokens'] += usage['prompt_tokens']
            self.stats['output_tokens'] += usage['completion_tokens']

            # Calculate cost using dynamic pricing from OpenRouter API
            cost = self.cost_calculator.calculate_cost(
                self.model,
                usage['prompt_tokens'],
                usage['completion_tokens']
            )
            self.stats['total_cost_usd'] += cost

            return complete_response, usage

    # =========================================================================
    # Stage 1: Load and Clean Pages
    # =========================================================================

    def clean_text(self, text: str) -> str:
        """Remove correction markers and LLM artifacts."""
        # Remove correction markers
        text = re.sub(r'\[CORRECTED:\d+\]', '', text)
        text = re.sub(r'\[FIXED:A4-\d+\]', '', text)

        # Remove LLM instruction artifacts
        text = re.sub(r"Here's the text with.*?marked:", '', text, flags=re.IGNORECASE)
        text = re.sub(r"Here are the.*?corrections:", '', text, flags=re.IGNORECASE)

        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        text = text.strip()

        return text

    def load_all_pages(self) -> list[dict]:
        """Load all pages with clean text."""
        print("\n" + "="*70)
        print("📄 Loading All Pages")
        print("="*70)

        pages = []
        page_files = sorted(self.corrected_dir.glob("page_*.json"))

        for page_file in page_files:
            if 'metadata' in page_file.name:
                continue

            try:
                with open(page_file) as f:
                    data = json.load(f)

                page_num = data.get('page_number')
                raw_text = data.get('llm_processing', {}).get('corrected_text', '')

                if not raw_text:
                    continue

                cleaned_text = self.clean_text(raw_text)

                pages.append({
                    "page_number": page_num,
                    "text": cleaned_text
                })

                self.stats['pages_loaded'] += 1

                if page_num % 100 == 0:
                    print(f"  ✓ Loaded {self.stats['pages_loaded']} pages...")

            except Exception as e:
                print(f"  ✗ Error loading {page_file.name}: {e}")

        print(f"\n✅ Loaded {len(pages)} pages")
        return pages

    # =========================================================================
    # Stage 2: Deep Structure with LLM
    # =========================================================================

    def build_full_book_text(self, pages: list[dict]) -> str:
        """Build complete book text with page markers for provenance."""
        parts = []
        for page in pages:
            parts.append(f"<!-- PAGE {page['page_number']} -->")
            parts.append(page['text'])
            parts.append("")  # Blank line between pages

        return "\n".join(parts)

    def assemble_paragraphs_from_boundaries(self, structure: dict, pages: list[dict]) -> dict:
        """
        Assemble chapter text from page ranges identified by LLM.

        Creates paragraphs (one per page) within each chapter for database storage.
        """
        # Create page lookup
        page_lookup = {p['page_number']: p['text'] for p in pages}

        for chapter in structure.get('chapters', []):
            start_page = chapter.get('start_page')
            end_page = chapter.get('end_page')
            chapter_num = chapter.get('number')

            # Create one paragraph per page within chapter
            paragraphs = []
            for page_num in range(start_page, end_page + 1):
                if page_num in page_lookup:
                    paragraphs.append({
                        "id": f"ch{chapter_num:02d}_p{len(paragraphs)+1:03d}",
                        "text": page_lookup[page_num],
                        "pages": [page_num],
                        "type": "body"
                    })

            chapter['paragraphs'] = paragraphs

        return structure

    def structure_book_deep(self, pages: list[dict]) -> dict:
        """
        Use LLM to semantically structure the entire book in one pass.

        This is the core intelligence - LLM reads whole book and creates
        proper semantic structure.
        """
        print("\n" + "="*70)
        print("🧠 Deep Structuring with LLM (Full Book Analysis)")
        print("="*70)

        # Build complete book text
        full_text = self.build_full_book_text(pages)

        token_estimate = len(full_text.split())
        gen_time_estimate = token_estimate / 60  # ~60 tok/s generation
        print(f"\n📊 Book stats:")
        print(f"   Pages: {len(pages)}")
        print(f"   Estimated input tokens: ~{token_estimate:,}")
        print(f"   Estimated output tokens: ~{token_estimate:,} (full structured JSON)")
        print(f"   Estimated cost: ~${token_estimate * 0.000003 + token_estimate * 0.000015:.2f}")
        print(f"\n⏱️  Timing estimate:")
        print(f"   Input processing: ~30-60 seconds")
        print(f"   Output generation: ~{gen_time_estimate/60:.0f} minutes ({token_estimate:,} tokens @ ~60 tok/s)")
        print(f"   Total: ~{(gen_time_estimate/60) + 1:.0f} minutes")
        print(f"\n🔄 Sending to LLM now (be patient, this is a LONG generation)...")
        print(f"   Model: {self.model}")
        print()
        sys.stdout.flush()  # Force output before long API call

        system_prompt = """You are an expert book structuring analyst. Your task is to analyze complete books and create deeply semantic JSON structure that preserves meaning, context, and organization.

You understand:
- True chapter boundaries (not just from table of contents)
- How paragraphs naturally group by topic, event, or argument
- When paragraphs span page breaks
- Section breaks within chapters
- Semantic relationships between content

Return only valid JSON, no other text."""

        user_prompt = f"""Analyze this complete book and identify its CHAPTER STRUCTURE only.

COMPLETE BOOK TEXT:
{full_text}

Return JSON identifying chapters (do NOT include paragraph-level detail):
{{
  "book": {{
    "title": "extracted from front matter",
    "author": "extracted from front matter",
    "total_pages": {len(pages)}
  }},
  "chapters": [
    {{
      "number": 1,
      "title": "actual chapter title from content",
      "start_page": 1,
      "end_page": 38,
      "summary": "2-3 sentence chapter summary describing main events/arguments"
    }},
    {{
      "number": 2,
      "title": "next chapter title",
      "start_page": 39,
      "end_page": 75,
      "summary": "2-3 sentence chapter summary"
    }}
  ]
}}

CRITICAL REQUIREMENTS:
1. Detect TRUE chapter boundaries by reading content (not just TOC)
2. Each chapter gets start_page and end_page range
3. Skip front/back matter (copyright, index, bibliography, etc.) - only main content chapters
4. Page markers like "<!-- PAGE 42 -->" show page breaks
5. Summaries should capture key events, people, or arguments in chapter

Return ONLY the JSON structure, nothing else."""

        try:
            response, usage = self.call_llm(system_prompt, user_prompt, temperature=0.0, stream=True)
            print("\n✅ LLM response complete! Parsing JSON structure...\n")
            sys.stdout.flush()

            # Extract JSON from response (handle cases with explanatory text)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                structure = json.loads(json_match.group(0))
            else:
                structure = json.loads(response)

            self.stats['chapters_detected'] = len(structure.get('chapters', []))

            print(f"✅ Deep structuring complete!")
            print(f"   Chapters detected: {self.stats['chapters_detected']}")
            print(f"   Input tokens: {usage.get('prompt_tokens', 0):,}")
            print(f"   Output tokens: {usage.get('completion_tokens', 0):,}")

            # Now assemble chapter text from page ranges
            print(f"\n📝 Assembling chapter text from page ranges...")
            structure = self.assemble_paragraphs_from_boundaries(structure, pages)

            # Count paragraphs after assembly
            for chapter in structure.get('chapters', []):
                self.stats['paragraphs_created'] += len(chapter.get('paragraphs', []))

            print(f"   Paragraphs created: {self.stats['paragraphs_created']}")

            return structure

        except Exception as e:
            print(f"\n❌ Deep structuring failed: {e}")
            print(f"   Falling back to simple structure...")

            # Fallback: simple single-chapter structure
            return {
                "book": {
                    "title": self.book_slug.replace('-', ' '),
                    "author": "Unknown",
                    "total_pages": len(pages)
                },
                "chapters": [{
                    "number": 1,
                    "title": "Full Book",
                    "start_page": 1,
                    "end_page": len(pages),
                    "summary": "Complete book content",
                    "paragraphs": [
                        {
                            "id": f"ch01_p{i:03d}",
                            "text": page['text'],
                            "pages": [page['page_number']],
                            "type": "body"
                        }
                        for i, page in enumerate(pages, 1)
                    ]
                }]
            }

    # =========================================================================
    # Stage 3: Generate Output Files
    # =========================================================================

    def save_chapter_files(self, structure: dict):
        """Save individual chapter files (JSON + Markdown)."""
        print("\n" + "="*70)
        print("📖 Creating Chapter Files")
        print("="*70)

        for chapter in structure.get('chapters', []):
            ch_num = chapter['number']

            # Save JSON
            chapter_json = self.chapters_dir / f"chapter_{ch_num:02d}.json"
            with open(chapter_json, 'w', encoding='utf-8') as f:
                json.dump(chapter, f, indent=2, ensure_ascii=False)

            # Save Markdown (human-readable)
            md_content = f"# Chapter {ch_num}: {chapter['title']}\n\n"
            md_content += f"*Pages {chapter['start_page']}-{chapter['end_page']}*\n\n"
            md_content += f"**Summary:** {chapter.get('summary', 'N/A')}\n\n"
            md_content += "---\n\n"

            for para in chapter.get('paragraphs', []):
                md_content += para['text'] + "\n\n"

            chapter_md = self.chapters_dir / f"chapter_{ch_num:02d}.md"
            with open(chapter_md, 'w', encoding='utf-8') as f:
                f.write(md_content)

            print(f"  ✓ Chapter {ch_num}: {len(chapter.get('paragraphs', []))} paragraphs")

        print(f"\n✅ Created {len(structure['chapters'])} chapter files")

    def create_semantic_chunks(self, structure: dict, chunk_size_paragraphs=10):
        """
        Create semantic chunks from structured paragraphs.

        Groups ~10 paragraphs per chunk for RAG/embedding.
        """
        print("\n" + "="*70)
        print("🔗 Creating Semantic Chunks")
        print("="*70)

        chunk_id = 1
        all_paragraphs = []

        # Collect all paragraphs with chapter context
        for chapter in structure.get('chapters', []):
            for para in chapter.get('paragraphs', []):
                all_paragraphs.append({
                    "chapter_num": chapter['number'],
                    "chapter_title": chapter['title'],
                    **para
                })

        # Group into chunks
        for i in range(0, len(all_paragraphs), chunk_size_paragraphs):
            chunk_paras = all_paragraphs[i:i + chunk_size_paragraphs]

            chunk_text = "\n\n".join(p['text'] for p in chunk_paras)

            chunk_data = {
                "chunk_id": chunk_id,
                "chapter": chunk_paras[0]['chapter_num'],
                "pages": [chunk_paras[0]['pages'][0], chunk_paras[-1]['pages'][-1]],
                "paragraph_ids": [p['id'] for p in chunk_paras],
                "text": chunk_text,
                "token_count": len(chunk_text.split())
            }

            chunk_file = self.chunks_dir / f"chunk_{chunk_id:03d}.json"
            with open(chunk_file, 'w', encoding='utf-8') as f:
                json.dump(chunk_data, f, indent=2, ensure_ascii=False)

            chunk_id += 1

        self.stats['chunks_created'] = chunk_id - 1
        print(f"✅ Created {self.stats['chunks_created']} semantic chunks")

    def create_full_book_markdown(self, structure: dict):
        """Create single full book markdown."""
        print("\n📖 Creating full book markdown...")

        book_info = structure['book']

        md = f"# {book_info['title']}\n\n"
        md += f"**By {book_info['author']}**\n\n"
        md += f"*{book_info['total_pages']} pages, {len(structure['chapters'])} chapters*\n\n"
        md += "---\n\n"

        for chapter in structure['chapters']:
            md += f"## Chapter {chapter['number']}: {chapter['title']}\n\n"
            md += f"*Pages {chapter['start_page']}-{chapter['end_page']}*\n\n"
            md += f"**Summary:** {chapter.get('summary', 'N/A')}\n\n"

            for para in chapter['paragraphs']:
                md += para['text'] + "\n\n"

        full_md_file = self.structured_dir / "full_book.md"
        with open(full_md_file, 'w', encoding='utf-8') as f:
            f.write(md)

        print(f"✅ Created full book markdown")

    def save_metadata(self, structure: dict):
        """Save processing metadata."""
        metadata = {
            "book_slug": self.book_slug,
            "book_info": structure['book'],
            "processing_date": datetime.now().isoformat(),
            "model": self.model,
            "stats": self.stats,
            "chapters": [
                {
                    "number": ch['number'],
                    "title": ch['title'],
                    "pages": [ch['start_page'], ch['end_page']],
                    "paragraph_count": len(ch.get('paragraphs', []))
                }
                for ch in structure['chapters']
            ]
        }

        metadata_file = self.structured_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        print(f"✅ Saved metadata")

    # =========================================================================
    # Main Pipeline
    # =========================================================================

    def process_book(self):
        """Run complete deep structuring pipeline."""
        print("="*70)
        print("📚 Deep Book Structuring Pipeline")
        print(f"   Book: {self.book_slug}")
        print(f"   Model: {self.model}")
        print("="*70)

        # Stage 1: Load pages
        pages = self.load_all_pages()

        # Stage 2: Deep structure with LLM
        structure = self.structure_book_deep(pages)

        # Stage 3: Generate outputs
        self.save_chapter_files(structure)
        self.create_semantic_chunks(structure, chunk_size_paragraphs=10)
        self.create_full_book_markdown(structure)
        self.save_metadata(structure)

        # Print summary
        print("\n" + "="*70)
        print("✅ Deep Book Structuring Complete")
        print("="*70)
        print(f"\n📊 Summary:")
        print(f"   Pages loaded: {self.stats['pages_loaded']}")
        print(f"   Chapters detected: {self.stats['chapters_detected']}")
        print(f"   Paragraphs created: {self.stats['paragraphs_created']}")
        print(f"   Chunks created: {self.stats['chunks_created']}")
        print(f"   Input tokens: {self.stats['input_tokens']:,}")
        print(f"   Output tokens: {self.stats['output_tokens']:,}")
        print(f"   Total cost: ${self.stats['total_cost_usd']:.2f}")
        print(f"\n📁 Output: {self.structured_dir}")
        print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python pipeline/structure.py <book-slug> [model]")
        print("Example: python pipeline/structure.py The-Accidental-President")
        print("         python pipeline/structure.py The-Accidental-President anthropic/claude-haiku-4")
        sys.exit(1)

    book_slug = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else None

    structurer = DeepBookStructurer(book_slug, model=model)
    structurer.process_book()


if __name__ == "__main__":
    main()