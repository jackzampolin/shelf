#!/usr/bin/env python3
import base64
import io
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def add_images_to_messages(messages: List[Dict], images: List, logger_instance: Optional[logging.Logger] = None) -> List[Dict]:
    log = logger_instance or logger

    user_msg_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]['role'] == 'user':
            user_msg_idx = i
            break

    if user_msg_idx is None:
        raise ValueError("No user message found to attach images to")

    original_content = messages[user_msg_idx]['content']

    if isinstance(original_content, list):
        content = original_content.copy()
    else:
        content = [{"type": "text", "text": original_content}]

    total_bytes = 0
    for idx, img in enumerate(images):
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=75)
        img_bytes = buffered.getvalue()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')
        total_bytes += len(img_bytes)

        log.debug(
            f"Encoded image {idx+1}/{len(images)}",
            image_index=idx,
            size_bytes=len(img_bytes),
            base64_length=len(img_b64)
        )

        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{img_b64}"
            }
        })

    messages = messages.copy()
    messages[user_msg_idx] = messages[user_msg_idx].copy()
    messages[user_msg_idx]['content'] = content

    log.debug(
        f"Attached {len(images)} images to user message",
        num_images=len(images),
        total_bytes=total_bytes,
        message_index=user_msg_idx,
        num_content_parts=len(content)
    )

    return messages
