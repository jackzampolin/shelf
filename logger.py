#!/usr/bin/env python3
"""
Unified pipeline logging system

Provides structured JSON logging with:
- Real-time progress tracking
- Cost tracking per operation
- Context preservation (scan_id, stage, page numbers)
- Machine-parseable logs for monitoring
- Backward compatible with print statements

LOG FILE LOCATIONS:
  ~/Documents/book_scans/<scan-id>/logs/{stage}_{timestamp}.jsonl

JSON SCHEMA:
  Required fields: timestamp, level, message, scan_id, stage
  Optional fields: page, progress, cost_usd, tokens, duration_seconds, error

USAGE:
  # Preferred: Context manager (auto-cleanup)
  with create_logger('scan-id', 'stage') as logger:
      logger.info('Processing...', page=42)
      logger.progress('Pages', current=10, total=100)

  # Alternative: Manual cleanup
  logger = create_logger('scan-id', 'stage')
  try:
      logger.info('Processing...')
  finally:
      logger.close()

THREAD SAFETY:
  - Logging calls are thread-safe (uses Python logging module)
  - Context modifications are protected by internal lock
  - File writes are atomic per log entry
"""

import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from contextlib import contextmanager


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        """Convert log record to JSON format."""
        log_data = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        if hasattr(record, 'scan_id'):
            log_data['scan_id'] = record.scan_id
        if hasattr(record, 'stage'):
            log_data['stage'] = record.stage
        if hasattr(record, 'page'):
            log_data['page'] = record.page
        if hasattr(record, 'progress'):
            log_data['progress'] = record.progress
        if hasattr(record, 'cost_usd'):
            log_data['cost_usd'] = record.cost_usd
        if hasattr(record, 'tokens'):
            log_data['tokens'] = record.tokens
        if hasattr(record, 'duration_seconds'):
            log_data['duration_seconds'] = record.duration_seconds
        if hasattr(record, 'error'):
            log_data['error'] = record.error

        return json.dumps(log_data)


class HumanFormatter(logging.Formatter):
    """Format log records for human-readable console output."""

    # Icons for different log levels
    ICONS = {
        'DEBUG': '🔍',
        'INFO': 'ℹ️',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '🚨'
    }

    def format(self, record: logging.LogRecord) -> str:
        """Convert log record to human-readable format."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        icon = self.ICONS.get(record.levelname, 'ℹ️')

        # Build the message
        parts = [f"[{timestamp}]", icon]

        # Add stage and page if present
        if hasattr(record, 'stage'):
            parts.append(f"[{record.stage}]")
        if hasattr(record, 'page'):
            parts.append(f"[page {record.page}]")

        parts.append(record.getMessage())

        # Add progress bar if present
        if hasattr(record, 'progress'):
            prog = record.progress
            pct = prog['percent']
            bar_width = 30
            filled = int(bar_width * pct / 100)
            bar = '█' * filled + '░' * (bar_width - filled)
            parts.append(f"\n    [{bar}] {pct:.1f}% ({prog['current']}/{prog['total']})")

        # Add cost if present
        if hasattr(record, 'cost_usd'):
            parts.append(f"(${record.cost_usd:.4f})")

        return ' '.join(parts)


class PipelineLogger:
    """
    Unified logger for pipeline operations.

    Writes both JSON (for machines) and human-readable (for console) logs.
    Maintains context across operations (scan_id, stage, etc.)
    """

    def __init__(
        self,
        scan_id: str,
        stage: str,
        log_dir: Optional[Path] = None,
        console_output: bool = True,
        json_output: bool = True,
        level: str = "INFO"
    ):
        """
        Initialize pipeline logger.

        Args:
            scan_id: Unique scan identifier (e.g., "modest-lovelace")
            stage: Pipeline stage (e.g., "ocr", "correct", "fix", "structure")
            log_dir: Directory for log files (default: ~/Documents/book_scans/<scan_id>/logs)
            console_output: Whether to output to console
            json_output: Whether to write JSON log file
            level: Logging level (DEBUG, INFO, WARNING, ERROR)
        """
        self.scan_id = scan_id
        self.stage = stage
        self.context = {}  # Additional context to include in all logs
        self._context_lock = threading.Lock()  # Thread-safe context modifications

        # Setup log directory
        if log_dir is None:
            log_dir = Path.home() / "Documents" / "book_scans" / scan_id / "logs"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create logger with unique name to avoid handler accumulation
        # Use instance id to ensure each PipelineLogger gets its own logging.Logger
        logger_name = f"pipeline.{scan_id}.{stage}.{id(self)}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.logger.propagate = False  # Don't propagate to parent loggers

        # Console handler (human-readable)
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(HumanFormatter())
            self.logger.addHandler(console_handler)

        # JSON file handler (machine-parseable)
        if json_output:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            json_file = self.log_dir / f"{stage}_{timestamp}.jsonl"
            json_handler = logging.FileHandler(json_file)
            json_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(json_handler)

            # Store log file path for reference
            self.log_file = json_file

    def _log(self, level: str, message: str, **kwargs):
        """Internal logging method with context."""
        # Merge context with kwargs (thread-safe)
        with self._context_lock:
            extra = {
                'scan_id': self.scan_id,
                'stage': self.stage,
                **self.context.copy(),  # Safe copy under lock
                **kwargs
            }

        # Create LogRecord with extra attributes
        self.logger.log(
            getattr(logging, level.upper()),
            message,
            extra=extra
        )

    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log('DEBUG', message, **kwargs)

    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log('INFO', message, **kwargs)

    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self._log('WARNING', message, **kwargs)

    def error(self, message: str, **kwargs):
        """Log error message."""
        self._log('ERROR', message, **kwargs)

    def critical(self, message: str, **kwargs):
        """Log critical message."""
        self._log('CRITICAL', message, **kwargs)

    def progress(
        self,
        message: str,
        current: int,
        total: int,
        **kwargs
    ):
        """
        Log progress update.

        Args:
            message: Progress description
            current: Current item number
            total: Total items
            **kwargs: Additional context (cost_usd, tokens, etc.)
        """
        percent = min(100.0, (current / total * 100) if total > 0 else 0)
        progress_data = {
            'current': current,
            'total': total,
            'percent': percent
        }

        self._log('INFO', message, progress=progress_data, **kwargs)

    def cost(self, message: str, cost_usd: float, **kwargs):
        """Log operation with cost tracking."""
        self._log('INFO', message, cost_usd=cost_usd, **kwargs)

    def page_event(self, message: str, page: int, **kwargs):
        """Log page-specific event."""
        self._log('INFO', message, page=page, **kwargs)

    def page_error(self, message: str, page: int, error: str, **kwargs):
        """Log page-specific error."""
        self._log('ERROR', message, page=page, error=error, **kwargs)

    def start_stage(self, **kwargs):
        """Log stage start with metadata."""
        self.info(f"Starting {self.stage} stage", **kwargs)

    def complete_stage(self, duration_seconds: float, **kwargs):
        """Log stage completion with duration."""
        self.info(
            f"Completed {self.stage} stage",
            duration_seconds=duration_seconds,
            **kwargs
        )

    @contextmanager
    def context_scope(self, **context):
        """
        Temporarily add context to all logs within scope.

        Example:
            with logger.context_scope(worker_id=1):
                logger.info("Processing...")  # Includes worker_id=1
        """
        old_context = self.context.copy()
        self.context.update(context)
        try:
            yield
        finally:
            self.context = old_context

    def set_context(self, **context):
        """Permanently add context to all future logs (thread-safe)."""
        with self._context_lock:
            self.context.update(context)

    def clear_context(self):
        """Clear all context (thread-safe)."""
        with self._context_lock:
            self.context = {}

    def close(self):
        """Close all handlers and flush logs."""
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.close()
        return False

    def __del__(self):
        """Cleanup on garbage collection."""
        try:
            self.close()
        except:
            pass  # Ignore errors during cleanup


def create_logger(
    scan_id: str,
    stage: str,
    **kwargs
) -> PipelineLogger:
    """
    Convenience function to create a pipeline logger.

    Args:
        scan_id: Unique scan identifier
        stage: Pipeline stage name
        **kwargs: Additional arguments for PipelineLogger

    Returns:
        Configured PipelineLogger instance
    """
    return PipelineLogger(scan_id, stage, **kwargs)


# Example usage
if __name__ == "__main__":
    # Create logger
    logger = create_logger("modest-lovelace", "correction")

    # Log various events
    logger.start_stage(pages=447, model="gpt-4o-mini")

    logger.info("Processing pages 1-447")

    # Progress tracking
    for i in range(1, 11):
        logger.progress(
            "Correcting pages",
            current=i * 45,
            total=447,
            cost_usd=i * 0.02
        )

    # Page events
    logger.page_event("Corrected successfully", page=42, errors_fixed=5)

    # Page errors
    logger.page_error(
        "Failed to correct",
        page=100,
        error="Invalid JSON response"
    )

    # Complete stage
    logger.complete_stage(duration_seconds=120.5, total_cost_usd=2.34)

    print(f"\nLog file: {logger.log_file}")
