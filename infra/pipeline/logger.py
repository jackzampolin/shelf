import json
import logging
import sys
from datetime import datetime
from pathlib import Path


class FlushingFileHandler(logging.FileHandler):
    """FileHandler that flushes after every emit for real-time log visibility."""
    def emit(self, record):
        super().emit(record)
        self.flush()


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        if hasattr(record, 'scan_id'):
            log_data['scan_id'] = record.scan_id
        if hasattr(record, 'stage'):
            log_data['stage'] = record.stage
        if hasattr(record, 'page'):
            log_data['page'] = record.page
        if hasattr(record, 'cost_usd'):
            log_data['cost_usd'] = record.cost_usd
        if hasattr(record, 'tokens'):
            log_data['tokens'] = record.tokens
        if hasattr(record, 'duration_seconds'):
            log_data['duration_seconds'] = record.duration_seconds
        if hasattr(record, 'error'):
            log_data['error'] = record.error

        return json.dumps(log_data)

class PipelineLogger:
    """Logger that writes to a single append-only JSONL file per stage.

    File handlers are created lazily on first log message to avoid
    creating empty log files when nothing is logged.
    """
    def __init__(
        self,
        scan_id: str,
        stage: str,
        log_dir: Path,
        console_output: bool = False,
        json_output: bool = True,
        level: str = "INFO",
        filename: str = None
    ):
        self.scan_id = scan_id
        self.stage = stage
        self.log_dir = Path(log_dir)
        self.console_output = console_output
        self.json_output = json_output
        self.level = level
        self.filename = filename or f"{stage}.jsonl"

        # Lazy initialization - handlers created on first log
        self._logger = None
        self._initialized = False
        self.log_file = None

    def _ensure_initialized(self):
        """Initialize logger and handlers on first use."""
        if self._initialized:
            return

        logger_name = f"pipeline.{self.scan_id}.{self.stage}.{id(self)}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(getattr(logging, self.level.upper()))
        self._logger.propagate = False

        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
            self._logger.addHandler(console_handler)

        if self.json_output:
            # Create log directory only when we actually need to write
            self.log_dir.mkdir(parents=True, exist_ok=True)
            # Single append-only file (no timestamp in filename)
            json_file = self.log_dir / self.filename
            # mode='a' for append
            json_handler = FlushingFileHandler(json_file, mode='a')
            json_handler.setFormatter(JSONFormatter())
            self._logger.addHandler(json_handler)
            self.log_file = json_file

        self._initialized = True

    @property
    def logger(self):
        """Get the underlying logger, initializing if needed."""
        self._ensure_initialized()
        return self._logger

    def _log(self, level: str, message: str, **kwargs):
        # Extract reserved logging parameters
        reserved_params = {}
        for param in ['exc_info', 'stack_info', 'stacklevel', 'extra']:
            if param in kwargs:
                reserved_params[param] = kwargs.pop(param)

        # Merge custom extra fields with any provided extra dict
        extra = {
            'scan_id': self.scan_id,
            'stage': self.stage,
            **kwargs
        }
        if 'extra' in reserved_params:
            extra.update(reserved_params.pop('extra'))

        self.logger.log(
            getattr(logging, level.upper()),
            message,
            extra=extra,
            **reserved_params
        )

    def debug(self, message: str, **kwargs):
        self._log('DEBUG', message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log('INFO', message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log('WARNING', message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log('ERROR', message, **kwargs)

    def close(self):
        # Only close if we actually initialized handlers
        if self._initialized and self._logger:
            for handler in self._logger.handlers[:]:
                handler.close()
                self._logger.removeHandler(handler)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except:
            pass


def create_logger(scan_id: str, stage: str, **kwargs) -> PipelineLogger:
    return PipelineLogger(scan_id, stage, **kwargs)
