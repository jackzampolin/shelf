#!/usr/bin/env python3
import time
import uuid
import random
import logging
import requests
from typing import Callable, Dict, Any, TypeVar, Optional

from .errors import MalformedResponseError

T = TypeVar('T')

class RetryPolicy:
    def __init__(self, logger: Optional[logging.Logger] = None, max_retries: int = 3):
        self.logger = logger or logging.getLogger(__name__)
        self.max_retries = max_retries

    def execute_with_retry(
        self,
        fn: Callable[[], T],
        payload: Dict[str, Any]
    ) -> T:
        model = payload.get('model', 'unknown')

        for attempt in range(max(1, self.max_retries)):
            try:
                self.logger.debug(
                    f"Retry attempt {attempt+1}/{max(1, self.max_retries)}",
                    model=model,
                    attempt=attempt+1,
                    max_retries=self.max_retries
                )

                result = fn()

                if attempt > 0:
                    self.logger.debug(
                        f"Request succeeded after {attempt+1} attempts",
                        model=model,
                        attempts=attempt+1
                    )

                return result

            except MalformedResponseError as e:
                if attempt < max(1, self.max_retries) - 1:
                    delay = 2.0 + random.uniform(-1.5, 1.5)
                    self.logger.debug(
                        f"Malformed response, retrying in {delay:.1f}s",
                        model=model,
                        attempt=attempt+1,
                        max_retries=self.max_retries,
                        error=str(e),
                        delay_seconds=delay
                    )
                    time.sleep(delay)
                    continue
                else:
                    self.logger.debug(
                        f"Malformed response on final attempt, raising",
                        model=model,
                        attempt=attempt+1,
                        error=str(e)
                    )
                    raise

            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code

                if not self._should_retry(e, attempt):
                    self.logger.debug(
                        f"HTTP error not retryable, raising",
                        model=model,
                        status_code=status_code,
                        attempt=attempt+1,
                        error=str(e)
                    )
                    raise

                delay = 2.0 + random.uniform(-1.5, 1.5)

                if status_code in [413, 422]:
                    self._inject_nonce(payload, status_code, attempt)

                self.logger.debug(
                    f"HTTP {status_code} error, retrying in {delay:.1f}s",
                    model=model,
                    status_code=status_code,
                    attempt=attempt+1,
                    max_retries=self.max_retries,
                    delay_seconds=delay,
                    nonce_injected=status_code in [413, 422]
                )

                time.sleep(delay)
                continue

            except requests.exceptions.Timeout:
                if attempt < max(1, self.max_retries) - 1:
                    delay = 2.0 + random.uniform(-1.5, 1.5)
                    self.logger.debug(
                        f"Request timeout, retrying in {delay:.1f}s",
                        model=model,
                        attempt=attempt+1,
                        max_retries=self.max_retries,
                        delay_seconds=delay
                    )
                    time.sleep(delay)
                    continue
                else:
                    self.logger.debug(
                        f"Request timeout on final attempt, raising",
                        model=model,
                        attempt=attempt+1
                    )
                    raise

    def _should_retry(self, error: requests.exceptions.HTTPError, attempt: int) -> bool:
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
            self.logger.debug(
                f"Injected nonce into text content",
                status_code=status_code,
                attempt=attempt+1,
                max_retries=self.max_retries,
                nonce=nonce
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
            self.logger.debug(
                f"Injected nonce into multipart content",
                status_code=status_code,
                attempt=attempt+1,
                max_retries=self.max_retries,
                nonce=nonce,
                num_parts=len(content),
                num_images=num_images
            )
