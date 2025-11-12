#!/usr/bin/env python3
import time
import uuid
import random
import logging
import requests
from typing import Callable, Dict, Any, TypeVar

from .errors import MalformedResponseError

logger = logging.getLogger(__name__)

T = TypeVar('T')

class RetryPolicy:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def execute_with_retry(
        self,
        fn: Callable[[], T],
        payload: Dict[str, Any]
    ) -> T:
        for attempt in range(max(1, self.max_retries)):
            try:
                return fn()

            except MalformedResponseError as e:
                if attempt < max(1, self.max_retries) - 1:
                    logger.warning(
                        f"Malformed response on attempt {attempt+1}/{self.max_retries}, retrying...",
                        error=str(e)
                    )
                    delay = 2.0 + random.uniform(-1.5, 1.5)
                    time.sleep(delay)
                    continue
                else:
                    raise

            except requests.exceptions.HTTPError as e:
                if not self._should_retry(e, attempt):
                    raise

                if e.response.status_code in [413, 422]:
                    self._inject_nonce(payload, e.response.status_code, attempt)

                delay = 2.0 + random.uniform(-1.5, 1.5)
                time.sleep(delay)
                continue

            except requests.exceptions.Timeout:
                if attempt < max(1, self.max_retries) - 1:
                    delay = 2.0 + random.uniform(-1.5, 1.5)
                    time.sleep(delay)
                    continue
                else:
                    raise

    def _should_retry(self, error: requests.exceptions.HTTPError, attempt: int) -> bool:
        """Check if error should be retried."""
        if attempt >= max(1, self.max_retries) - 1:
            return False

        status = error.response.status_code

        if status >= 500:
            return True

        if status in [413, 422, 429]:
            return True

        return False

    def _inject_nonce(self, payload: Dict[str, Any], status_code: int, attempt: int):
        nonce = uuid.uuid4().hex[:16]

        messages = payload.get('messages', [])
        if not messages:
            return

        user_msg_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]['role'] == 'user':
                user_msg_idx = i
                break

        if user_msg_idx is None:
            return

        msg = messages[user_msg_idx]
        content = msg.get('content', '')

        if isinstance(content, str):
            msg['content'] = f"{content}\n<!-- retry_{attempt}_id: {nonce} -->"
            logger.warning(
                f"Retry {attempt+1}/{self.max_retries} for {status_code} - added nonce to text content"
            )

        elif isinstance(content, list):
            content_copy = []
            for item in content:
                item_copy = item.copy()
                if item_copy.get('type') == 'text':
                    item_copy['text'] = f"{item_copy.get('text', '')}\n<!-- retry_{attempt}_id: {nonce} -->"
                content_copy.append(item_copy)

            msg['content'] = content_copy
            num_images = sum(1 for c in content if c.get('type') == 'image_url')
            logger.warning(
                f"Retry {attempt+1}/{self.max_retries} for {status_code} - "
                f"added nonce {nonce} to multipart content ({len(content)} parts, {num_images} images)"
            )
