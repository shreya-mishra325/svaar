"""Bounded, deadline-aware workers for read-only model inference only.

Never submit tool handlers or database sessions here. A timed-out model response
can finish in a worker, but its abandoned result cannot dispatch actions.
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


class TurnTimeoutError(Exception):
    """The absolute turn deadline expired or inference capacity is exhausted."""


class InferencePool:
    """Bound in-flight inference, including abandoned requests, without a task queue."""

    def __init__(self, workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="svaar-inference"
        )
        self._slots = threading.BoundedSemaphore(workers)

    def call(self, operation: Callable[[], T], *, deadline: float) -> T:
        """Wait only until the deadline; do not free capacity until work actually ends."""
        remaining = deadline - monotonic()
        if remaining <= 0 or not self._slots.acquire(blocking=False):
            raise TurnTimeoutError("Inference deadline or capacity reached")
        try:
            future = self._executor.submit(operation)
        except RuntimeError:
            self._slots.release()
            raise TurnTimeoutError("Inference pool is closed") from None
        future.add_done_callback(lambda _: self._slots.release())
        try:
            return future.result(timeout=max(0, deadline - monotonic()))
        except TimeoutError:
            future.cancel()
            raise TurnTimeoutError("Turn deadline reached") from None

    def close(self) -> None:
        """Refuse new work and cancel queued work; running inference has HTTP timeouts."""
        self._executor.shutdown(wait=False, cancel_futures=True)
