# Semaphore Control Specification

**Status**: Specification  
**Source**: CA-008 (Incrementalist RunDotNetCommandTask.cs pattern)

## Overview

The semaphore control pattern limits concurrent execution to a configurable number of parallel tasks. This prevents resource exhaustion and enables controlled scaling.

## Core Pattern

### Python asyncio Implementation

```python
import asyncio
from dataclasses import dataclass
from typing import List, Callable, TypeVar, Optional
from contextlib import asynccontextmanager

T = TypeVar('T')

class SemaphoreExecutor:
    """
    Execute tasks with semaphore-based concurrency control.
    
    Adapted from Incrementalist's RunDotNetCommandTask.cs pattern.
    """
    
    def __init__(
        self,
        parallel_limit: int = 4,
        timeout_seconds: int = 300,
        continue_on_error: bool = False
    ):
        self._semaphore = asyncio.Semaphore(parallel_limit)
        self._parallel_limit = parallel_limit
        self._timeout_seconds = timeout_seconds
        self._continue_on_error = continue_on_error
        self._failed_tasks: List[TaskResult] = []
        self._cancel_event = asyncio.Event()
    
    async def run_all(
        self, 
        tasks: List['AgentTask']
    ) -> 'ExecutionResults':
        """
        Execute all tasks with controlled parallelism.
        
        Args:
            tasks: List of tasks to execute
            
        Returns:
            ExecutionResults with success/failure details
        """
        start_time = asyncio.get_event_loop().time()
        results = []
        
        async def run_with_semaphore(task: AgentTask) -> TaskResult:
            # Check for cancellation before acquiring semaphore
            if self._cancel_event.is_set():
                return TaskResult(
                    task=task,
                    status="cancelled",
                    duration_ms=0
                )
            
            async with self._semaphore:
                # Check again after acquiring
                if self._cancel_event.is_set():
                    return TaskResult(
                        task=task,
                        status="cancelled", 
                        duration_ms=0
                    )
                
                return await self._execute_task(task)
        
        # Create tasks for all work items
        async_tasks = [
            asyncio.create_task(run_with_semaphore(task))
            for task in tasks
        ]
        
        # Gather results
        results = await asyncio.gather(*async_tasks, return_exceptions=True)
        
        # Process results
        succeeded = []
        failed = []
        cancelled = []
        
        for result in results:
            if isinstance(result, Exception):
                failed.append(TaskResult(
                    task=None,
                    status="failed",
                    duration_ms=0,
                    error=str(result)
                ))
            elif result.status == "success":
                succeeded.append(result)
            elif result.status == "cancelled":
                cancelled.append(result)
            else:
                failed.append(result)
        
        end_time = asyncio.get_event_loop().time()
        
        return ExecutionResults(
            total=len(tasks),
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
            duration_ms=int((end_time - start_time) * 1000)
        )
    
    async def _execute_task(self, task: 'AgentTask') -> 'TaskResult':
        """Execute a single task with timeout."""
        start = asyncio.get_event_loop().time()
        
        try:
            async with asyncio.timeout(self._timeout_seconds):
                output = await task.execute()
                
            duration = int((asyncio.get_event_loop().time() - start) * 1000)
            return TaskResult(
                task=task,
                status="success",
                duration_ms=duration,
                output=output
            )
            
        except asyncio.TimeoutError:
            duration = int((asyncio.get_event_loop().time() - start) * 1000)
            result = TaskResult(
                task=task,
                status="timeout",
                duration_ms=duration,
                error=f"Timeout after {self._timeout_seconds}s"
            )
            self._handle_failure(result)
            return result
            
        except Exception as e:
            duration = int((asyncio.get_event_loop().time() - start) * 1000)
            result = TaskResult(
                task=task,
                status="failed",
                duration_ms=duration,
                error=str(e)
            )
            self._handle_failure(result)
            return result
    
    def _handle_failure(self, result: 'TaskResult') -> None:
        """Handle task failure based on configuration."""
        self._failed_tasks.append(result)
        
        if not self._continue_on_error:
            # Signal cancellation to pending tasks
            self._cancel_event.set()
```

## Timeout Control

### Linked Cancellation Pattern

```python
@asynccontextmanager
async def timeout_context(
    timeout_seconds: int,
    on_timeout: Optional[Callable] = None
):
    """
    Create a cancellable context with timeout.
    
    Adapted from Incrementalist's linked CancellationTokenSource pattern.
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            yield
    except asyncio.TimeoutError:
        if on_timeout:
            await on_timeout()
        raise
```

### Usage

```python
async def run_agent(artifact: str) -> str:
    async with timeout_context(300, on_timeout=lambda: log_timeout(artifact)):
        return await invoke_agent(artifact)
```

## Backpressure Handling

When all semaphore slots are occupied, new tasks wait:

```python
# With parallel_limit=4:
# - Tasks 1-4 start immediately
# - Task 5 waits for any of 1-4 to complete
# - When task 2 completes, task 5 starts
# - And so on...
```

## Configuration

### Recommended Limits

| Resource Type | Recommended Limit | Rationale |
|--------------|-------------------|-----------|
| API Calls | 2-4 | Rate limiting |
| File Processing | 8-16 | I/O bound |
| Validation | 16-32 | CPU bound, fast |
| Mixed | 4-8 | Balanced |

### Environment Variables

```bash
# Override default parallel limit
AGENT33_PARALLEL_LIMIT=8

# Override default timeout
AGENT33_TASK_TIMEOUT=600
```

## Monitoring

The semaphore executor emits metrics:

```python
logger.info(
    "parallel_execution_complete",
    total=len(tasks),
    succeeded=len(succeeded),
    failed=len(failed),
    parallel_limit=self._parallel_limit,
    duration_ms=duration_ms,
    avg_task_ms=duration_ms // len(tasks) if tasks else 0
)
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| parent | `README.md` | Parallel execution overview |
| uses | `EXECUTION_MODES.md` | Mode-specific behavior |
| outputs-to | `../analytics/METRICS_CATALOG.md` | Execution metrics |
