"""Resize embedding vector to configurable dimension and switch to HNSW index.

This migration:
1. Drops the old IVFFlat index (which requires manual re-training and has
   lower recall than HNSW).
2. Drops the old vector(1536) column (data loss -- see note below).
3. Re-creates the column at the configured dimension (default 768 for
   nomic-embed-text via Ollama).
4. Creates an HNSW index with cosine distance ops -- self-tuning, no
   training step, better recall at comparable speed.

NOTE: This migration is destructive for existing embeddings.  If you have
stored embeddings in memory_documents, they were generated at the old
dimension and cannot be resized.  After running this migration, re-ingest
all documents so new embeddings are generated at the correct dimension.

The default dimension (768) matches nomic-embed-text.  Override via the
EMBEDDING_DIM environment variable if you use a different embedding model.

Revision ID: 002
Revises: 001
Create Date: 2026-03-25 00:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str = "001"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None

# Read dimension from env at migration time; default to 768 (nomic-embed-text).
_EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))

# HNSW build parameters.
# m=16: max connections per node (good trade-off for 768-dim vectors).
# ef_construction=200: build-time search width (higher = better recall, slower build).
_HNSW_M = 16
_HNSW_EF_CONSTRUCTION = 200


def _table_exists(table_name: str) -> bool:
    """Check whether *table_name* exists in the current database."""
    result = op.get_bind().execute(sa.text("SELECT to_regclass(:tbl)"), {"tbl": table_name})
    return result.scalar() is not None


def _upgrade_table(table_name: str) -> None:
    """Drop old IVFFlat index/column and re-create with HNSW at target dim."""
    op.execute(f"DROP INDEX IF EXISTS ix_{table_name}_embedding")
    op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS embedding")
    op.execute(f"ALTER TABLE {table_name} ADD COLUMN embedding vector({_EMBEDDING_DIM})")
    op.execute(
        f"CREATE INDEX ix_{table_name}_embedding "
        f"ON {table_name} USING hnsw (embedding vector_cosine_ops) "
        f"WITH (m = {_HNSW_M}, ef_construction = {_HNSW_EF_CONSTRUCTION})"
    )


def _downgrade_table(table_name: str) -> None:
    """Revert table back to vector(1536) with IVFFlat index."""
    op.execute(f"DROP INDEX IF EXISTS ix_{table_name}_embedding")
    op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS embedding")
    op.execute(f"ALTER TABLE {table_name} ADD COLUMN embedding vector(1536)")
    op.execute(
        f"CREATE INDEX ix_{table_name}_embedding "
        f"ON {table_name} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def upgrade() -> None:
    _upgrade_table("memory_documents")

    # memory_records may not exist yet (created by ORM at startup).
    if _table_exists("memory_records"):
        _upgrade_table("memory_records")


def downgrade() -> None:
    # memory_records may not exist yet (created by ORM at startup).
    if _table_exists("memory_records"):
        _downgrade_table("memory_records")

    _downgrade_table("memory_documents")
