"""Checkpointer factory. SQLite for local runs (the connection lives for the
process lifetime — local-first app; the OS reclaims it on exit). A Postgres
saver slots in behind the same factory when firm sync lands (Phase 4)."""
import logging
from pathlib import Path

logger = logging.getLogger("yunaki.kernel.checkpoints")


async def open_sqlite_checkpointer(path: str | Path):
    """Open (creating parent dirs) the SQLite checkpointer at `path`."""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(path))
    logger.info("sqlite checkpointer ready path=%s", path)
    return AsyncSqliteSaver(conn)
