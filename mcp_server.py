#!/usr/bin/env python3
"""
MCP Server for AR Research Book Library

Provides Claude Desktop with direct access to processed books through MCP protocol.

Tools:
- list_books: List all books in the library
- get_book_info: Get detailed information about a specific book
- search_book: Full-text search across book content
- get_chapter: Retrieve a specific chapter with full text
- get_chunk: Retrieve a semantic chunk by ID
- get_chunk_context: Get chunk with surrounding context
- list_chapters: List all chapters in a book
- list_chunks: List all chunks in a book (with optional chapter filter)

Usage:
    Add to Claude Desktop config, then restart Claude:
    {
      "mcpServers": {
        "ar-research": {
          "command": "python",
          "args": ["/path/to/ar-research/mcp_server.py"]
        }
      }
    }
"""

import json
import sys
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.library import LibraryIndex

# MCP imports
try:
    from mcp.server.models import InitializationOptions
    from mcp.server import NotificationOptions, Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    print("ERROR: mcp package not installed. Run: uv pip install mcp", file=sys.stderr)
    sys.exit(1)


class BookQueryServer:
    """Core book query functionality."""

    def __init__(self):
        self.library = LibraryIndex()
        self.storage_root = self.library.storage_root

    def list_books(self) -> List[Dict[str, Any]]:
        """List all books in the library with basic metadata."""
        books = []
        for book_slug, book_data in self.library.data['books'].items():
            for scan in book_data['scans']:
                books.append({
                    'book_slug': book_slug,
                    'scan_id': scan['scan_id'],
                    'title': book_data['title'],
                    'author': book_data['author'],
                    'isbn': book_data.get('isbn'),
                    'year': book_data.get('year'),
                    'status': scan['status'],
                    'pages': scan.get('pages', 0),
                    'cost_usd': scan.get('cost_usd', 0.0),
                    'date_added': scan['date_added']
                })
        return books

    def get_book_info(self, scan_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific book scan."""
        scan_info = self.library.get_scan_info(scan_id)
        if not scan_info:
            raise ValueError(f'Book not found: {scan_id}')

        # Get structure metadata if available
        structure_path = self.storage_root / scan_id / 'structured' / 'metadata.json'
        structure_meta = None
        if structure_path.exists():
            with open(structure_path) as f:
                structure_meta = json.load(f)

        result = {
            'scan_id': scan_id,
            'title': scan_info['title'],
            'author': scan_info['author'],
            'isbn': scan_info.get('isbn'),
            'year': scan_info.get('year'),
            'scan': scan_info['scan']
        }

        if structure_meta:
            result['chapters'] = structure_meta.get('chapters', [])
            result['stats'] = structure_meta.get('stats', {})

        return result

    def search_book(self, scan_id: str, query: str, context_lines: int = 2) -> List[Dict[str, Any]]:
        """Full-text search across book content with context."""
        chunks_dir = self.storage_root / scan_id / 'structured' / 'chunks'
        if not chunks_dir.exists():
            raise ValueError(f'No structured content found for: {scan_id}')

        query_lower = query.lower()
        results = []

        for chunk_file in sorted(chunks_dir.glob('chunk_*.json')):
            with open(chunk_file) as f:
                chunk = json.load(f)

            text = chunk.get('text', '')
            if query_lower not in text.lower():
                continue

            # Find all occurrences in this chunk
            lines = text.split('\n')
            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    # Extract context
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    context = '\n'.join(lines[start:end])

                    results.append({
                        'chunk_id': chunk['chunk_id'],
                        'chapter': chunk['chapter'],
                        'pages': chunk['pages'],
                        'match_line': line,
                        'context': context,
                        'position': i
                    })

        return results

    def get_chapter(self, scan_id: str, chapter_number: int) -> Dict[str, Any]:
        """Retrieve a specific chapter with full text and metadata."""
        chapter_dir = self.storage_root / scan_id / 'structured' / 'chapters'
        chapter_file = chapter_dir / f'chapter_{chapter_number:02d}.json'

        if not chapter_file.exists():
            raise ValueError(f'Chapter {chapter_number} not found in {scan_id}')

        with open(chapter_file) as f:
            chapter_data = json.load(f)

        # Also get the markdown version if available
        md_file = chapter_dir / f'chapter_{chapter_number:02d}.md'
        if md_file.exists():
            with open(md_file) as f:
                chapter_data['markdown'] = f.read()

        return chapter_data

    def get_chunk(self, scan_id: str, chunk_id: int) -> Dict[str, Any]:
        """Retrieve a specific semantic chunk by ID."""
        chunks_dir = self.storage_root / scan_id / 'structured' / 'chunks'
        chunk_file = chunks_dir / f'chunk_{chunk_id:03d}.json'

        if not chunk_file.exists():
            raise ValueError(f'Chunk {chunk_id} not found in {scan_id}')

        with open(chunk_file) as f:
            return json.load(f)

    def get_chunk_context(self, scan_id: str, chunk_id: int, before: int = 1, after: int = 1) -> Dict[str, Any]:
        """Get a chunk with surrounding chunks for context."""
        chunks_dir = self.storage_root / scan_id / 'structured' / 'chunks'

        # Get all available chunks
        all_chunks = sorted(chunks_dir.glob('chunk_*.json'))
        chunk_ids = [int(f.stem.split('_')[1]) for f in all_chunks]

        if chunk_id not in chunk_ids:
            raise ValueError(f'Chunk {chunk_id} not found in {scan_id}')

        # Determine range
        start_id = max(1, chunk_id - before)
        end_id = min(max(chunk_ids), chunk_id + after)

        result = {
            'main_chunk_id': chunk_id,
            'context_range': [start_id, end_id],
            'chunks': []
        }

        for cid in range(start_id, end_id + 1):
            chunk_file = chunks_dir / f'chunk_{cid:03d}.json'
            if chunk_file.exists():
                with open(chunk_file) as f:
                    chunk_data = json.load(f)
                    chunk_data['is_main'] = (cid == chunk_id)
                    result['chunks'].append(chunk_data)

        return result

    def list_chapters(self, scan_id: str) -> List[Dict[str, Any]]:
        """List all chapters in a book with metadata."""
        structure_path = self.storage_root / scan_id / 'structured' / 'metadata.json'
        if not structure_path.exists():
            raise ValueError(f'No structured content found for: {scan_id}')

        with open(structure_path) as f:
            metadata = json.load(f)

        return metadata.get('chapters', [])

    def list_chunks(self, scan_id: str, chapter: Optional[int] = None) -> List[Dict[str, Any]]:
        """List all chunks in a book, optionally filtered by chapter."""
        chunks_dir = self.storage_root / scan_id / 'structured' / 'chunks'
        if not chunks_dir.exists():
            raise ValueError(f'No structured content found for: {scan_id}')

        chunks = []
        for chunk_file in sorted(chunks_dir.glob('chunk_*.json')):
            with open(chunk_file) as f:
                chunk = json.load(f)

            # Filter by chapter if requested
            if chapter is not None and chunk.get('chapter') != chapter:
                continue

            # Return summary (no full text)
            chunks.append({
                'chunk_id': chunk['chunk_id'],
                'chapter': chunk['chapter'],
                'pages': chunk['pages'],
                'paragraph_ids': chunk.get('paragraph_ids', []),
                'token_count': chunk.get('token_count', 0),
                'preview': chunk.get('text', '')[:200] + '...'
            })

        return chunks


# Initialize MCP server
server = Server("ar-research-books")
query_server = BookQueryServer()


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available MCP tools."""
    return [
        types.Tool(
            name="list_books",
            description="List all books in the library with basic metadata (title, author, scan_id, status)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="get_book_info",
            description="Get detailed information about a specific book including chapters and processing stats",
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string", "description": "The scan identifier (e.g., 'modest-lovelace')"}
                },
                "required": ["scan_id"]
            }
        ),
        types.Tool(
            name="search_book",
            description="Full-text search across book content with context around matches",
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string", "description": "The scan identifier"},
                    "query": {"type": "string", "description": "Search query (case-insensitive)"},
                    "context_lines": {"type": "integer", "description": "Number of context lines (default: 2)", "default": 2}
                },
                "required": ["scan_id", "query"]
            }
        ),
        types.Tool(
            name="get_chapter",
            description="Retrieve a specific chapter with full text and metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string", "description": "The scan identifier"},
                    "chapter_number": {"type": "integer", "description": "Chapter number (1-indexed)"}
                },
                "required": ["scan_id", "chapter_number"]
            }
        ),
        types.Tool(
            name="get_chunk",
            description="Retrieve a specific semantic chunk by ID (chunks are ~5-page segments for RAG)",
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string", "description": "The scan identifier"},
                    "chunk_id": {"type": "integer", "description": "Chunk ID number (1-indexed)"}
                },
                "required": ["scan_id", "chunk_id"]
            }
        ),
        types.Tool(
            name="get_chunk_context",
            description="Get a chunk with surrounding chunks for broader context",
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string", "description": "The scan identifier"},
                    "chunk_id": {"type": "integer", "description": "Chunk ID number"},
                    "before": {"type": "integer", "description": "Number of chunks before (default: 1)", "default": 1},
                    "after": {"type": "integer", "description": "Number of chunks after (default: 1)", "default": 1}
                },
                "required": ["scan_id", "chunk_id"]
            }
        ),
        types.Tool(
            name="list_chapters",
            description="List all chapters in a book with metadata (number, title, page ranges)",
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string", "description": "The scan identifier"}
                },
                "required": ["scan_id"]
            }
        ),
        types.Tool(
            name="list_chunks",
            description="List all chunks in a book with summary info, optionally filtered by chapter",
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string", "description": "The scan identifier"},
                    "chapter": {"type": "integer", "description": "Optional: filter by chapter number"}
                },
                "required": ["scan_id"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """Handle tool execution requests."""
    if arguments is None:
        arguments = {}

    try:
        if name == "list_books":
            result = query_server.list_books()

        elif name == "get_book_info":
            result = query_server.get_book_info(arguments["scan_id"])

        elif name == "search_book":
            result = query_server.search_book(
                arguments["scan_id"],
                arguments["query"],
                arguments.get("context_lines", 2)
            )

        elif name == "get_chapter":
            result = query_server.get_chapter(
                arguments["scan_id"],
                int(arguments["chapter_number"])
            )

        elif name == "get_chunk":
            result = query_server.get_chunk(
                arguments["scan_id"],
                int(arguments["chunk_id"])
            )

        elif name == "get_chunk_context":
            result = query_server.get_chunk_context(
                arguments["scan_id"],
                int(arguments["chunk_id"]),
                arguments.get("before", 1),
                arguments.get("after", 1)
            )

        elif name == "list_chapters":
            result = query_server.list_chapters(arguments["scan_id"])

        elif name == "list_chunks":
            result = query_server.list_chunks(
                arguments["scan_id"],
                arguments.get("chapter")
            )

        else:
            raise ValueError(f"Unknown tool: {name}")

        # Return result as formatted JSON
        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]


async def main():
    """Main entry point for MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="ar-research-books",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
