#!/usr/bin/env python3
"""Request phase tracking for worker pool.

Functions for updating and querying request lifecycle phases.
"""
import time
from typing import Dict

from ..schemas import RequestPhase, RequestStatus


def update_request_phase(worker_pool, request_id: str, phase: RequestPhase):
    """Update the phase of an active request."""
    with worker_pool.request_tracking_lock:
        if request_id in worker_pool.active_requests:
            status = worker_pool.active_requests[request_id]
            status.phase = phase
            status.phase_entered_at = time.time()


def get_active_requests(worker_pool) -> Dict[str, RequestStatus]:
    """Get snapshot of all active requests and their current phases.

    Returns:
        Dict mapping request_id to RequestStatus (copied for thread safety)
    """
    with worker_pool.request_tracking_lock:
        return {
            req_id: RequestStatus(
                request_id=status.request_id,
                phase=status.phase,
                queued_at=status.queued_at,
                phase_entered_at=status.phase_entered_at,
                retry_count=status.retry_count,
                rate_limit_eta=status.rate_limit_eta
            )
            for req_id, status in worker_pool.active_requests.items()
        }
