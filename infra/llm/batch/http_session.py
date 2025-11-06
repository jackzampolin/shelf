#!/usr/bin/env python3
"""Thread-local HTTP session management."""

import threading
import requests


class ThreadLocalSessionManager:

    def __init__(self):
        self._thread_local = threading.local()

    def get_session(self) -> requests.Session:
        if not hasattr(self._thread_local, 'session'):
            self._thread_local.session = self._create_session()
        return self._thread_local.session

    def _create_session(self) -> requests.Session:
        session = requests.Session()

        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=0
        )
        session.mount('https://', adapter)
        session.mount('http://', adapter)

        return session
