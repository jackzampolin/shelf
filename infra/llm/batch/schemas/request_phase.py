#!/usr/bin/env python3
from enum import Enum


class RequestPhase(str, Enum):
    QUEUED = "queued"
    RATE_LIMITED = "rate_limited"
    DEQUEUED = "dequeued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
