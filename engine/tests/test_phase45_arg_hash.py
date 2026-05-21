"""Tests for canonical argument hashing (Phase 45)."""

from __future__ import annotations

from agent33.security.arg_hash import canonical_arg_hash


class TestCanonicalArgHash:
    """Determinism, key order, nested objects, type stability."""

    def test_empty_arguments(self) -> None:
        result = canonical_arg_hash("shell", {})
        assert result.startswith("sha256:")
        assert len(result) == len("sha256:") + 64

    def test_deterministic_across_calls(self) -> None:
        args = {"command": "ls -la", "timeout": 30}
        a = canonical_arg_hash("shell", args)
        b = canonical_arg_hash("shell", args)
        assert a == b

    def test_key_order_independence(self) -> None:
        args_a = {"z": 1, "a": 2, "m": 3}
        args_b = {"a": 2, "m": 3, "z": 1}
        assert canonical_arg_hash("tool", args_a) == canonical_arg_hash("tool", args_b)

    def test_different_tool_names_produce_different_hashes(self) -> None:
        args = {"command": "echo hello"}
        h1 = canonical_arg_hash("shell", args)
        h2 = canonical_arg_hash("file_ops", args)
        assert h1 != h2

    def test_different_arguments_produce_different_hashes(self) -> None:
        h1 = canonical_arg_hash("shell", {"command": "rm /tmp/safe"})
        h2 = canonical_arg_hash("shell", {"command": "rm /"})
        assert h1 != h2

    def test_nested_objects(self) -> None:
        args = {"config": {"nested": {"deep": True}, "list": [1, 2, 3]}}
        result = canonical_arg_hash("tool", args)
        assert result.startswith("sha256:")
        # Nested key ordering should be stable
        args_reordered = {"config": {"list": [1, 2, 3], "nested": {"deep": True}}}
        assert canonical_arg_hash("tool", args) == canonical_arg_hash("tool", args_reordered)

    def test_type_stability_int_vs_float(self) -> None:
        # JSON serializes 1 and 1.0 differently: "1" vs "1.0"
        h_int = canonical_arg_hash("tool", {"value": 1})
        h_float = canonical_arg_hash("tool", {"value": 1.0})
        # These will differ because json.dumps distinguishes int from float
        # This is correct behavior: type matters for argument matching
        assert h_int != h_float

    def test_boolean_values(self) -> None:
        h_true = canonical_arg_hash("tool", {"flag": True})
        h_false = canonical_arg_hash("tool", {"flag": False})
        assert h_true != h_false

    def test_null_value(self) -> None:
        h_null = canonical_arg_hash("tool", {"key": None})
        h_empty = canonical_arg_hash("tool", {"key": ""})
        assert h_null != h_empty

    def test_special_characters_in_values(self) -> None:
        args = {"path": "/tmp/file with spaces & symbols!@#$%"}
        result = canonical_arg_hash("shell", args)
        assert result.startswith("sha256:")
        # Should be deterministic
        assert result == canonical_arg_hash("shell", args)
