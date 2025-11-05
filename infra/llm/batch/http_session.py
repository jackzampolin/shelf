#!/usr/bin/env python3
"""
Thread-local HTTP session management for batch LLM requests.

Each worker thread gets its own HTTP session to prevent connection pooling
issues across concurrent workers. Sessions are configured with minimal pooling
to avoid stale connections.
"""

import threading
import requests


class ThreadLocalSessionManager:
    """
    HTTP session pool with one session per worker thread.

    Prevents connection pooling issues across concurrent workers by creating
    isolated sessions per thread. Each session has minimal pooling configured
    to avoid stale connections.

    Usage:
        manager = ThreadLocalSessionManager()
        session = manager.get_session()
        response = session.post(url, ...)
    """

    def __init__(self):
        """Initialize thread-local storage."""
        self._thread_local = threading.local()

    def get_session(self) -> requests.Session:
        """
        Get or create HTTP session for current thread.

        Creates isolated session per thread to prevent connection pooling issues
        across concurrent workers. Each session has minimal pooling to avoid
        stale connections.

        Returns:
            requests.Session instance for current thread
        """
        if not hasattr(self._thread_local, 'session'):
            self._thread_local.session = self._create_session()
        return self._thread_local.session

    def _create_session(self) -> requests.Session:
        """
        Create new session with minimal connection pooling.

        Configuration:
        - pool_connections=1: Only keep 1 connection to OpenRouter
        - pool_maxsize=1: Never pool more than 1 connection
        - max_retries=0: We handle retries ourselves at request level

        Returns:
            Configured requests.Session instance
        """
        session = requests.Session()

        # Configure adapter with minimal connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=0
        )
        session.mount('https://', adapter)
        session.mount('http://', adapter)

        return session
