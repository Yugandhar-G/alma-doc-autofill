"""RunManager — the compiled-graph registry.

Replaces per-module _GRAPH globals: one process-lifetime object holding each
package's compiled graph, built lazily under a lock (graph compilation opens
the checkpointer, which must happen exactly once per key)."""
import asyncio
from typing import Any, Awaitable, Callable


class RunManager:
    def __init__(self) -> None:
        self._graphs: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def get_or_build(self, key: str, build: Callable[[], Awaitable[Any]]) -> Any:
        """The compiled graph for `key`, building it on first request. The
        double-check under the lock keeps concurrent first requests from
        compiling twice."""
        graph = self._graphs.get(key)
        if graph is not None:
            return graph
        async with self._lock:
            graph = self._graphs.get(key)
            if graph is None:
                graph = await build()
                self._graphs[key] = graph
        return graph
