# MCP Server Setup Guide

The Scanshelf MCP server provides Claude Desktop with direct access to your processed book library. This enables natural language queries against your book collection directly from Claude chat.

## What is MCP?

**Model Context Protocol (MCP)** is a standard protocol that allows LLMs like Claude to access external data sources and tools. By running the Scanshelf MCP server, you can:

- List books in your library
- Search across all book content
- Retrieve specific chapters or chunks
- Query with context-aware results

## Installation

### 1. Install MCP Package

```bash
# From project root
source .venv/bin/activate
uv pip install -e .
```

This will install the `mcp` package along with other dependencies.

### 2. Test the Server

Before configuring Claude Desktop, verify the server works:

```bash
# Run the server (it will wait for stdin)
python mcp_server.py
```

In another terminal, test with a simple query:

```bash
# Test list_books command
echo '{"tool": "list_books", "arguments": {}}' | python mcp_server.py
```

You should see JSON output with your book list. Press Ctrl+C to stop the server.

## Claude Desktop Configuration

### 1. Find Claude Desktop Config

The configuration file location varies by platform:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### 2. Add Scanshelf Server

Edit `claude_desktop_config.json` and add the MCP server configuration:

```json
{
  "mcpServers": {
    "scanshelf": {
      "command": "python",
      "args": ["/absolute/path/to/scanshelf/mcp_server.py"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/scanshelf"
      }
    }
  }
}
```

**Important:**
- Replace `/absolute/path/to/scanshelf` with your actual project path
- Use absolute paths, not relative paths or `~`
- On macOS/Linux, find your path with: `pwd` in the project directory

### Example Configuration

```json
{
  "mcpServers": {
    "scanshelf": {
      "command": "python",
      "args": ["/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/mcp_server.py"],
      "env": {
        "PYTHONPATH": "/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf"
      }
    }
  }
}
```

### 3. Restart Claude Desktop

After editing the config:
1. Quit Claude Desktop completely (Cmd+Q on macOS)
2. Relaunch Claude Desktop
3. The MCP server will start automatically when needed

## Using the MCP Server

Once configured, you can query your books naturally in Claude chat:

### Example Queries

**List all books:**
```
What books do you have in the library?
```

**Search for content:**
```
Search for mentions of "Harry Truman" in modest-lovelace
```

**Get chapter information:**
```
Show me chapter 3 from the Accidental President book (modest-lovelace)
```

**Get semantic chunks:**
```
Get chunk 15 from modest-lovelace with surrounding context
```

## Available Tools

The MCP server provides 8 tools:

### 1. list_books
List all books with metadata (title, author, scan_id, pages, cost).

### 2. get_book_info
Get detailed information about a specific book including chapters and processing statistics.

**Parameters:**
- `scan_id`: The scan identifier (e.g., "modest-lovelace")

### 3. search_book
Full-text search across book content with context around matches.

**Parameters:**
- `scan_id`: The scan identifier
- `query`: Search query (case-insensitive)
- `context_lines`: Number of context lines (default: 2)

### 4. get_chapter
Retrieve a specific chapter with full text and metadata.

**Parameters:**
- `scan_id`: The scan identifier
- `chapter_number`: Chapter number (1-indexed)

### 5. get_chunk
Retrieve a specific semantic chunk by ID. Chunks are ~5-page segments optimized for RAG.

**Parameters:**
- `scan_id`: The scan identifier
- `chunk_id`: Chunk ID number (1-indexed)

### 6. get_chunk_context
Get a chunk with surrounding chunks for broader context.

**Parameters:**
- `scan_id`: The scan identifier
- `chunk_id`: Chunk ID number
- `before`: Number of chunks before (default: 1)
- `after`: Number of chunks after (default: 1)

### 7. list_chapters
List all chapters in a book with metadata (number, title, page ranges).

**Parameters:**
- `scan_id`: The scan identifier

### 8. list_chunks
List all chunks in a book with summary info, optionally filtered by chapter.

**Parameters:**
- `scan_id`: The scan identifier
- `chapter`: Optional chapter number filter

## Troubleshooting

### Server Not Connecting

1. **Check the path**: Ensure absolute paths in `claude_desktop_config.json`
2. **Verify Python**: Test that `python mcp_server.py` works from command line
3. **Check dependencies**: Run `uv pip install -e .` to ensure all packages installed

### "Book not found" Errors

The MCP server uses your local `~/Documents/book_scans/library.json` catalog. Ensure:
- Books have been added to the library (`ar library list`)
- Books have completed the structure stage (`ar status <scan-id>`)
- The `structured/` directory exists with `metadata.json`, `chapters/`, and `chunks/`

### View Server Logs

Claude Desktop logs MCP server output. To debug:

1. **macOS**: `~/Library/Logs/Claude/mcp-server-scanshelf.log`
2. **Windows**: `%APPDATA%\Claude\logs\mcp-server-scanshelf.log`
3. **Linux**: `~/.local/share/Claude/logs/mcp-server-scanshelf.log`

## Architecture

```
Claude Desktop
      ↓
  MCP Protocol (stdin/stdout)
      ↓
  mcp_server.py
      ↓
  tools/library.py → ~/Documents/book_scans/
                     ├── library.json (catalog)
                     └── <scan-id>/
                         ├── structured/
                         │   ├── chapters/
                         │   ├── chunks/
                         │   └── metadata.json
                         └── ...
```

The MCP server:
1. Receives tool call requests from Claude via stdin
2. Uses the LibraryIndex to access book data
3. Queries structured JSON files (chapters, chunks, metadata)
4. Returns results via stdout in MCP format

## Next Steps

- Add more books with `ar library ingest <directory>`
- Process books through the full pipeline with `ar pipeline <scan-id>`
- Query your collection naturally from Claude Desktop
- For programmatic access, see `docs/FLASK_API.md` (coming soon)

## See Also

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [Claude Desktop Documentation](https://claude.ai/desktop)
- [Scanshelf CLI Guide](../README.md)
