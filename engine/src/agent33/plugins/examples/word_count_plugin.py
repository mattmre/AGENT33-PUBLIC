"""Word-count example plugin demonstrating the AGENT-33 plugin SDK.

This plugin exposes a single capability: counting words, characters, and lines
in a text string.  It serves as the canonical reference implementation for
``PluginBase`` and the full plugin lifecycle.

Usage:
    1. Discover the ``word_count/`` plugin directory via ``PluginRegistry.discover()``.
    2. Load and enable the plugin.
    3. Call ``plugin.execute(input_text)`` to obtain counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent33.plugins.base import PluginBase
from agent33.plugins.manifest import (
    PluginManifest,
    PluginPermission,
    PluginStatus,
)

if TYPE_CHECKING:
    from agent33.plugins.context import PluginContext

# Default upper bound on accepted text length (characters).
_DEFAULT_MAX_TEXT_LENGTH: int = 10_000


def _build_manifest() -> PluginManifest:
    """Build the canonical manifest for the word-count plugin.

    This is the authoritative source of truth; the YAML manifest file
    (``engine/examples/plugins/word_count/manifest.yaml``) must mirror these values.
    """
    return PluginManifest(
        name="word-count",
        version="1.0.0",
        description="Count words, characters, and lines in a text string.",
        author="AGENT-33 Contributors",
        homepage="https://github.com/mattmre/AGENT33",
        entry_point="word_count_plugin:WordCountPlugin",
        permissions=[PluginPermission.CONFIG_READ],
        status=PluginStatus.ACTIVE,
        tags=["example", "text-processing", "utility"],
    )


class WordCountPlugin(PluginBase):
    """Reference plugin that counts words, characters, and lines.

    Configuration (passed via ``PluginContext.plugin_config``):
        max_text_length (int):
            Upper character-count limit for ``execute()``.  Texts longer
            than this raise ``ValueError``.  Default: 10 000.
    """

    # ------------------------------------------------------------------
    # Class-level manifest helper
    # ------------------------------------------------------------------

    @staticmethod
    def default_manifest() -> PluginManifest:
        """Return the manifest without needing an instance."""
        return _build_manifest()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, manifest: PluginManifest, context: PluginContext) -> None:
        super().__init__(manifest, context)
        self._max_text_length: int = _DEFAULT_MAX_TEXT_LENGTH
        self._initialized: bool = False

    async def on_load(self) -> None:
        """Validate configuration and mark the plugin as ready."""
        config: dict[str, Any] = self._context.plugin_config
        raw = config.get("max_text_length", _DEFAULT_MAX_TEXT_LENGTH)

        if not isinstance(raw, int) or isinstance(raw, bool):
            raise ValueError(f"max_text_length must be an int, got {type(raw).__name__}: {raw!r}")
        if raw <= 0:
            raise ValueError(f"max_text_length must be positive, got {raw}")

        self._max_text_length = raw
        self._initialized = True
        self._logger.info("WordCountPlugin loaded (max_text_length=%d)", self._max_text_length)

    async def on_enable(self) -> None:
        """Log activation."""
        self._logger.info("WordCountPlugin enabled")

    async def on_disable(self) -> None:
        """Log deactivation."""
        self._logger.info("WordCountPlugin disabled")

    async def on_unload(self) -> None:
        """Release state."""
        self._initialized = False
        self._logger.info("WordCountPlugin unloaded")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def max_text_length(self) -> int:
        """The configured maximum text length."""
        return self._max_text_length

    @property
    def is_initialized(self) -> bool:
        """Whether ``on_load()`` has completed successfully."""
        return self._initialized

    def execute(self, input_text: str) -> dict[str, int]:
        """Count words, characters, and lines in *input_text*.

        Args:
            input_text: The text to analyse.

        Returns:
            A dict with keys ``word_count``, ``char_count``, and ``line_count``.

        Raises:
            TypeError:  If *input_text* is not a ``str``.
            ValueError: If the text exceeds ``max_text_length``.
        """
        if not isinstance(input_text, str):
            raise TypeError(f"input_text must be a str, got {type(input_text).__name__}")

        if len(input_text) > self._max_text_length:
            raise ValueError(
                f"Text length {len(input_text)} exceeds max_text_length ({self._max_text_length})"
            )

        word_count = len(input_text.split()) if input_text else 0
        char_count = len(input_text)
        line_count = input_text.count("\n") + 1 if input_text else 0

        return {
            "word_count": word_count,
            "char_count": char_count,
            "line_count": line_count,
        }
