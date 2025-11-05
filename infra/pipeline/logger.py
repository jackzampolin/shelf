import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


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
    def __init__(
        self,
        scan_id: str,
        stage: str,
        log_dir: Path,
        console_output: bool = False,
        json_output: bool = True,
        level: str = "INFO"
    ):
        self.scan_id = scan_id
        self.stage = stage

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        logger_name = f"pipeline.{scan_id}.{stage}.{id(self)}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.logger.propagate = False

        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
            self.logger.addHandler(console_handler)

        if json_output:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            json_file = self.log_dir / f"{stage}_{timestamp}.jsonl"
            json_handler = logging.FileHandler(json_file)
            json_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(json_handler)
            self.log_file = json_file

    def _log(self, level: str, message: str, **kwargs):
        extra = {
            'scan_id': self.scan_id,
            'stage': self.stage,
            **kwargs
        }

        self.logger.log(
            getattr(logging, level.upper()),
            message,
            extra=extra
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
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

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
