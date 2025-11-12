#!/usr/bin/env python3
import base64
import io
from typing import List, Dict


def add_images_to_messages(messages: List[Dict], images: List) -> List[Dict]:
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

    for img in images:
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=75)
        img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{img_b64}"
            }
        })

    messages = messages.copy()
    messages[user_msg_idx] = messages[user_msg_idx].copy()
    messages[user_msg_idx]['content'] = content

    return messages
