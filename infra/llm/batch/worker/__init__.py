"""Worker pool for parallel LLM request execution.

The WorkerPool manages a thread pool that processes LLM requests in parallel:

1. **Queue Management** (queue.py)
   - Pull requests from priority queue
   - Check if all work is done

2. **Rate Limiting** (rate_limit.py)
   - Enforce rate limits before execution
   - Re-queue rate-limited requests

3. **Execution** (pool.py → ../executor.py)
   - Execute requests via RequestExecutor
   - Handle thread lifecycle

4. **Result Handling** (handlers.py)
   - Success: Store result, call on_result callback
   - Retry: Re-queue with jitter, track attempts
   - Failure: Store failed result, emit event
   - Crash: Log error, store failure result

5. **Phase Tracking** (tracking.py)
   - Track request lifecycle (QUEUED → DEQUEUED → EXECUTING → COMPLETED/FAILED)
   - Query active request states

## Usage

Most users don't interact with WorkerPool directly - use LLMBatchClient instead:

    from infra.llm.batch import LLMBatchClient

    client = LLMBatchClient(max_workers=10, logger=logger)
    results = client.process_batch(requests)

The client instantiates and manages the WorkerPool internally.

## Components

- **pool.py** (~200 lines): Main WorkerPool orchestration
- **handlers.py** (~160 lines): Result handling (success/retry/failure/crash)
- **queue.py** (~35 lines): Request queue management
- **rate_limit.py** (~50 lines): Rate limit checking
- **tracking.py** (~40 lines): Request phase tracking
"""
from .pool import WorkerPool

__all__ = ['WorkerPool']
