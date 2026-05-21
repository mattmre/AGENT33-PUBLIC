"""Tests for the dead-letter queue (automation.dead_letter)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from agent33.automation.dead_letter import DeadLetterItem, DeadLetterQueue, set_metrics


@pytest.fixture()
def dlq() -> DeadLetterQueue:
    """Return a fresh DeadLetterQueue instance."""
    return DeadLetterQueue()


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


class TestCapture:
    """Tests for DeadLetterQueue.capture()."""

    def test_capture_returns_unique_id_and_stores_item(self, dlq: DeadLetterQueue) -> None:
        """capture() should return a UUID string and persist the item internally."""
        item_id = dlq.capture("trigger-a", {"key": "val"}, "boom")

        assert isinstance(item_id, str)
        assert len(item_id) == 36  # UUID format: 8-4-4-4-12

        items = dlq.list_failed()
        assert len(items) == 1
        item = items[0]
        assert item.item_id == item_id
        assert item.trigger_name == "trigger-a"
        assert item.payload == {"key": "val"}
        assert item.error == "boom"
        assert item.retried is False

    def test_capture_converts_exception_to_string(self, dlq: DeadLetterQueue) -> None:
        """When an Exception object is passed as *error*, it must be stringified."""
        item_id = dlq.capture("t", {}, ValueError("bad value"))

        items = dlq.list_failed()
        assert items[0].error == "bad value"
        assert items[0].item_id == item_id

    def test_capture_emits_metrics_when_collector_installed(self, dlq: DeadLetterQueue) -> None:
        """capture() should call increment and observe on the metrics collector."""
        collector = MagicMock()
        with patch("agent33.automation.dead_letter._metrics", collector):
            dlq.capture("t", {}, "err")

        collector.increment.assert_called_once_with("dead_letter_queue_captures_total", {})
        collector.observe.assert_called_once_with("dead_letter_queue_depth", 1.0, {})


# ---------------------------------------------------------------------------
# list_failed
# ---------------------------------------------------------------------------


class TestListFailed:
    """Tests for DeadLetterQueue.list_failed()."""

    def test_list_failed_empty_queue(self, dlq: DeadLetterQueue) -> None:
        """list_failed() on an empty queue should return an empty list."""
        assert dlq.list_failed() == []

    def test_list_failed_returns_newest_first(self, dlq: DeadLetterQueue) -> None:
        """Items should be ordered by captured_at descending (newest first)."""
        # Insert three items with monotonically increasing timestamps.
        with patch("agent33.automation.dead_letter.time") as mock_time:
            mock_time.time.side_effect = [100.0, 200.0, 300.0]
            dlq.capture("first", {}, "e1")
            dlq.capture("second", {}, "e2")
            dlq.capture("third", {}, "e3")

        items = dlq.list_failed()
        assert len(items) == 3
        assert items[0].trigger_name == "third"
        assert items[1].trigger_name == "second"
        assert items[2].trigger_name == "first"

    def test_list_failed_respects_limit(self, dlq: DeadLetterQueue) -> None:
        """list_failed(limit=N) should return at most N items."""
        for i in range(5):
            dlq.capture(f"t-{i}", {}, f"err-{i}")

        items = dlq.list_failed(limit=2)
        assert len(items) == 2


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------


class TestRetry:
    """Tests for DeadLetterQueue.retry()."""

    def test_retry_marks_item_and_returns_it(self, dlq: DeadLetterQueue) -> None:
        """retry() should set retried=True and return the same DeadLetterItem."""
        item_id = dlq.capture("t", {"x": 1}, "fail")

        returned = dlq.retry(item_id)

        assert isinstance(returned, DeadLetterItem)
        assert returned.retried is True
        assert returned.item_id == item_id
        assert returned.trigger_name == "t"
        assert returned.payload == {"x": 1}

    def test_retry_nonexistent_raises_key_error(self, dlq: DeadLetterQueue) -> None:
        """retry() with a missing ID must raise KeyError with the item ID."""
        with pytest.raises(KeyError, match="not-a-real-id"):
            dlq.retry("not-a-real-id")

    def test_retry_is_idempotent(self, dlq: DeadLetterQueue) -> None:
        """Calling retry() twice on the same item should succeed both times."""
        item_id = dlq.capture("t", {}, "e")
        first = dlq.retry(item_id)
        second = dlq.retry(item_id)
        assert first.retried is True
        assert second.retried is True
        assert first is second  # same object in the dict


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------


class TestPurge:
    """Tests for DeadLetterQueue.purge()."""

    def test_purge_removes_old_items_and_keeps_recent(self, dlq: DeadLetterQueue) -> None:
        """purge() should delete items older than the threshold and keep newer ones."""
        now = time.time()

        with patch("agent33.automation.dead_letter.time") as mock_time:
            # Insert an old item (captured 600s ago) and a recent one (captured 10s ago).
            mock_time.time.return_value = now - 600
            dlq.capture("old-trigger", {}, "old error")

            mock_time.time.return_value = now - 10
            dlq.capture("new-trigger", {}, "new error")

            # purge() also calls time.time() for cutoff calculation.
            mock_time.time.return_value = now
            removed = dlq.purge(older_than_seconds=300)

        assert removed == 1
        remaining = dlq.list_failed()
        assert len(remaining) == 1
        assert remaining[0].trigger_name == "new-trigger"

    def test_purge_empty_queue_returns_zero(self, dlq: DeadLetterQueue) -> None:
        """purge() on an empty queue should return 0 and not raise."""
        assert dlq.purge(older_than_seconds=0) == 0

    def test_purge_all_items(self, dlq: DeadLetterQueue) -> None:
        """purge() with a large window relative to capture times removes everything."""
        now = time.time()

        with patch("agent33.automation.dead_letter.time") as mock_time:
            # Capture 4 items at a fixed past timestamp.
            mock_time.time.return_value = now - 100
            for i in range(4):
                dlq.capture(f"t-{i}", {}, f"e-{i}")

            # Purge with cutoff = now - 50, so all items at now-100 are older.
            mock_time.time.return_value = now
            removed = dlq.purge(older_than_seconds=50)

        assert removed == 4
        assert dlq.list_failed() == []


# ---------------------------------------------------------------------------
# set_metrics module function
# ---------------------------------------------------------------------------


class TestSetMetrics:
    """Tests for the module-level set_metrics() wiring function."""

    def test_set_metrics_installs_collector(self, dlq: DeadLetterQueue) -> None:
        """After set_metrics(), capture() should invoke the installed collector."""
        collector = MagicMock()
        original = None
        try:
            import agent33.automation.dead_letter as dlm

            original = dlm._metrics
            set_metrics(collector)
            dlq.capture("t", {}, "e")
            collector.increment.assert_called_once()
            collector.observe.assert_called_once()
        finally:
            # Restore the original value to avoid polluting other tests.
            import agent33.automation.dead_letter as dlm

            dlm._metrics = original
