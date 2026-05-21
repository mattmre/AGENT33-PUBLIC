"""BM25 index warm-up from existing LongTermMemory records.

On startup, the BM25 index is empty.  This module loads existing records
from PostgreSQL in pages and adds them to the BM25 index so keyword
search works immediately without waiting for new ingestions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.memory.bm25 import BM25Index
    from agent33.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)


async def warm_up_bm25(
    long_term_memory: LongTermMemory,
    bm25_index: BM25Index,
    page_size: int = 200,
    max_records: int = 10_000,
) -> int:
    """Load existing memory records into the BM25 index.

    Reads pages of records from PostgreSQL and adds their content
    to the BM25 index.  Returns the total number of records loaded.

    Parameters
    ----------
    long_term_memory:
        The PostgreSQL-backed memory store.
    bm25_index:
        The in-memory BM25 index to populate.
    page_size:
        Number of records per page (default 200).
    max_records:
        Maximum total records to load (default 10,000).
    """
    loaded = 0
    offset = 0

    while loaded < max_records:
        batch_size = min(page_size, max_records - loaded)
        records = await long_term_memory.scan(limit=batch_size, offset=offset)
        if not records:
            break

        # Use batch add for performance (O(n) instead of O(n^2))
        docs_to_add: list[tuple[str, dict[str, Any] | None]] = [
            (record.text, record.metadata) for record in records
        ]
        bm25_index.add_documents(docs_to_add)
        loaded += len(docs_to_add)

        offset += len(records)
        logger.info("bm25_warmup_progress", extra={"loaded": loaded, "batch": len(records)})

    logger.info("bm25_warmup_complete", extra={"total_loaded": loaded})
    return loaded
