"""Firm memory — the recall substrate every deep agent reasons over.

A thin service over the matter store's memory rows (add_memory / list_memories)
plus prompt rendering that lets model output *cite* what it was shown. v1
retrieval is deterministic (firm-scoped filters + recency); the embedding seam
for pgvector is documented in service.py and left unfilled on purpose.
"""
from app.kernel.memory.service import MemoryService

__all__ = ["MemoryService"]
