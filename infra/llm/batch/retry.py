#!/usr/bin/env python3
from typing import Optional


def classify_error(error: Exception) -> str:
    error_str = str(error).lower()
    if 'timeout' in error_str:
        return 'timeout'
    elif '5' in error_str and ('server' in error_str or 'error' in error_str):
        return '5xx'
    elif '429' in error_str:
        return '429_rate_limit'
    elif '413' in error_str:
        return '413_payload_too_large'
    elif '422' in error_str:
        return '422_unprocessable'
    elif '4' in error_str and ('client' in error_str or 'error' in error_str):
        return '4xx'
    else:
        return 'unknown'


def is_retryable(error_type: Optional[str]) -> bool:
    retryable = [
        'timeout',
        '5xx',
        '429_rate_limit',
        '413_payload_too_large',
        '422_unprocessable',
        'unknown'
    ]
    return error_type in retryable


def extract_retry_after(error: Exception) -> Optional[int]:
    try:
        import requests
        if isinstance(error, requests.exceptions.HTTPError):
            if hasattr(error, 'response') and error.response is not None:
                retry_after = error.response.headers.get('Retry-After')
                if retry_after:
                    try:
                        return int(retry_after)
                    except ValueError:
                        return None
    except:
        pass
    return None
