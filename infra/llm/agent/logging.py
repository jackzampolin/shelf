import json
import copy
from typing import Dict, List, Optional
from pathlib import Path


def strip_images_from_messages(messages: List[Dict]) -> List[Dict]:
    cleaned_messages = []
    for msg in messages:
        cleaned_msg = msg.copy()
        content = cleaned_msg.get('content')
        if isinstance(content, list):
            cleaned_content = []
            for item in content:
                if item.get('type') == 'image_url':
                    url = item.get('image_url', {}).get('url', '')
                    cleaned_content.append({
                        'type': 'image_url',
                        'image_url': {
                            'url': '[IMAGE_DATA_REMOVED]',
                            'original_size_bytes': len(url)
                        }
                    })
                else:
                    cleaned_content.append(item)
            cleaned_msg['content'] = cleaned_content
        cleaned_messages.append(cleaned_msg)
    return cleaned_messages


def clean_run_log(log: Dict) -> Dict:
    cleaned = copy.deepcopy(log)
    if 'initial_messages' in cleaned:
        cleaned['initial_messages'] = strip_images_from_messages(cleaned['initial_messages'])
    for iteration in cleaned.get('iterations', []):
        if iteration.get('llm_response') and iteration['llm_response'].get('reasoning_details'):
            cleaned_reasoning = []
            for detail in iteration['llm_response']['reasoning_details']:
                cleaned_detail = {
                    'type': detail.get('type'),
                    'id': detail.get('id'),
                    'format': detail.get('format'),
                    'index': detail.get('index'),
                    'data_size_bytes': len(detail.get('data', '')) if detail.get('data') else 0,
                }
                cleaned_reasoning.append(cleaned_detail)
            iteration['llm_response']['reasoning_details'] = cleaned_reasoning
    return cleaned


def save_run_log(log: Dict, log_dir: Path, run_timestamp: str, log_filename: Optional[str] = None) -> Optional[Path]:
    if not log_dir:
        return None
    log_dir.mkdir(parents=True, exist_ok=True)
    cleaned_log = clean_run_log(log)

    if log_filename:
        run_log_path = log_dir / log_filename
    else:
        run_log_path = log_dir / f"run-{run_timestamp}.json"
    with open(run_log_path, 'w') as f:
        json.dump(cleaned_log, f, indent=2)
    return run_log_path
