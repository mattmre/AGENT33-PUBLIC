"""Ingestion adapters for various knowledge source types.

Each adapter implements ``fetch(source) -> list[str]`` returning text chunks
ready for embedding and storage. No external parsing libraries are used;
RSS is parsed with stdlib ``xml.etree.ElementTree`` and HTML is stripped
via regex.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from xml.etree.ElementTree import ParseError, fromstring  # noqa: S405

import httpx
import structlog

if TYPE_CHECKING:
    from agent33.knowledge.models import KnowledgeSource

logger = structlog.get_logger()

_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Maximum items to extract from an RSS feed
_RSS_MAX_ITEMS = 50

# Maximum characters per chunk for web / local adapters
_CHUNK_CHARS = 1200

# Allowed local file extensions
_LOCAL_EXTENSIONS = {".txt", ".md"}


def _strip_html(text: str) -> str:
    """Remove HTML tags with a simple regex."""
    return _HTML_TAG_RE.sub("", text).strip()


def _chunk_text(text: str, chunk_size: int = _CHUNK_CHARS) -> list[str]:
    """Split *text* into chunks of at most *chunk_size* characters."""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end
    return chunks


@runtime_checkable
class IngestionAdapter(Protocol):
    """Protocol for knowledge ingestion adapters."""

    async def fetch(self, source: KnowledgeSource) -> list[str]:
        """Fetch text chunks from the given source."""
        ...


class RSSAdapter:
    """Fetches and parses RSS / Atom feeds.

    Uses ``httpx`` for HTTP and stdlib ``xml.etree.ElementTree`` for parsing.
    Extracts ``<item>`` (RSS 2.0) and ``<entry>`` (Atom) elements, pulling
    ``<title>`` + ``<description>`` or ``<content>``.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def fetch(self, source: KnowledgeSource) -> list[str]:
        if not source.url:
            return []

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(source.url)
            response.raise_for_status()

        xml_text = response.text
        try:
            root = fromstring(xml_text)  # noqa: S314
        except ParseError as exc:
            logger.warning("rss_parse_failed", source_id=source.id, error=str(exc))
            return []

        chunks: list[str] = []

        # RSS 2.0: <channel> -> <item>
        for item in root.iter("item"):
            if len(chunks) >= _RSS_MAX_ITEMS:
                break
            title = item.findtext("title", default="")
            description = item.findtext("description", default="")
            text = _strip_html(f"{title}\n{description}".strip())
            if text:
                chunks.append(text)

        # Atom: <feed> -> <entry>
        # Atom uses namespaces; iterate with both bare and namespaced tags.
        _atom_ns = "http://www.w3.org/2005/Atom"
        _atom_entry_tags = ["entry", f"{{{_atom_ns}}}entry"]
        for tag in _atom_entry_tags:
            for entry in root.iter(tag):
                if len(chunks) >= _RSS_MAX_ITEMS:
                    break
                entry_title = (
                    entry.findtext("title", default="")
                    or entry.findtext(f"{{{_atom_ns}}}title", default="")
                    or ""
                )
                entry_content = (
                    entry.findtext("content", default="")
                    or entry.findtext(f"{{{_atom_ns}}}content", default="")
                    or entry.findtext("summary", default="")
                    or entry.findtext(f"{{{_atom_ns}}}summary", default="")
                    or ""
                )
                text = _strip_html(f"{entry_title}\n{entry_content}".strip())
                if text:
                    chunks.append(text)

        logger.info("rss_fetched", source_id=source.id, items=len(chunks))
        return chunks


class GitHubAdapter:
    """Fetches README and top-level markdown files from a GitHub repo.

    Uses the GitHub REST API. The ``source.url`` should be in the format
    ``https://github.com/{owner}/{repo}`` or just ``{owner}/{repo}``.
    """

    def __init__(self, timeout: float = 30.0, max_chars_per_file: int = 2000) -> None:
        self._timeout = timeout
        self._max_chars = max_chars_per_file

    def _parse_owner_repo(self, url: str) -> tuple[str, str]:
        """Extract (owner, repo) from a GitHub URL or shorthand."""
        # Strip trailing slashes and .git suffix
        cleaned = url.rstrip("/")
        if cleaned.endswith(".git"):
            cleaned = cleaned[:-4]

        # Handle full URLs
        if "github.com" in cleaned:
            parts = cleaned.split("github.com/")[-1].split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]

        # Handle shorthand: owner/repo
        parts = cleaned.split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1]

        raise ValueError(f"Cannot parse GitHub owner/repo from: {url!r}")

    async def fetch(self, source: KnowledgeSource) -> list[str]:
        if not source.url:
            return []

        owner, repo = self._parse_owner_repo(source.url)
        chunks: list[str] = []
        headers = {"Accept": "application/vnd.github.v3+json"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # Fetch README
            readme_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            try:
                resp = await client.get(readme_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    content_b64 = data.get("content", "")
                    if content_b64:
                        decoded = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                        chunks.append(decoded[: self._max_chars])
            except Exception as exc:
                logger.warning(
                    "github_readme_fetch_failed",
                    owner=owner,
                    repo=repo,
                    error=str(exc),
                )

            # Fetch tree to find additional .md files
            tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
            try:
                resp = await client.get(tree_url, headers=headers)
                if resp.status_code == 200:
                    tree = resp.json().get("tree", [])
                    md_paths = [
                        entry["path"]
                        for entry in tree
                        if entry.get("type") == "blob"
                        and entry["path"].endswith(".md")
                        and "/" not in entry["path"]  # top-level only
                        and entry["path"].upper() != "README.MD"
                    ]
                    for md_path in md_paths[:10]:  # limit to 10 files
                        file_url = (
                            f"https://api.github.com/repos/{owner}/{repo}/contents/{md_path}"
                        )
                        file_resp = await client.get(file_url, headers=headers)
                        if file_resp.status_code == 200:
                            file_data = file_resp.json()
                            content_b64 = file_data.get("content", "")
                            if content_b64:
                                decoded = base64.b64decode(content_b64).decode(
                                    "utf-8", errors="replace"
                                )
                                chunks.append(decoded[: self._max_chars])
            except Exception as exc:
                logger.warning(
                    "github_tree_fetch_failed",
                    owner=owner,
                    repo=repo,
                    error=str(exc),
                )

        logger.info("github_fetched", source_id=source.id, chunks=len(chunks))
        return chunks


class WebAdapter:
    """Fetches a web page, strips HTML tags, and returns text chunks."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def fetch(self, source: KnowledgeSource) -> list[str]:
        if not source.url:
            return []

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(source.url)
            response.raise_for_status()

        cleaned = _strip_html(response.text)
        chunks = _chunk_text(cleaned)
        logger.info("web_fetched", source_id=source.id, chunks=len(chunks))
        return chunks


class LocalFolderAdapter:
    """Reads ``.txt`` and ``.md`` files from a local folder."""

    async def fetch(self, source: KnowledgeSource) -> list[str]:
        if not source.local_path:
            return []

        folder = Path(source.local_path)
        if not folder.is_dir():
            logger.warning("local_folder_not_found", path=str(folder))
            return []

        chunks: list[str] = []
        for file_path in sorted(folder.rglob("*")):
            if file_path.suffix.lower() not in _LOCAL_EXTENSIONS:
                continue
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                file_chunks = _chunk_text(content)
                chunks.extend(file_chunks)
            except OSError as exc:
                logger.warning(
                    "local_file_read_failed",
                    path=str(file_path),
                    error=str(exc),
                )

        logger.info("local_folder_fetched", source_id=source.id, chunks=len(chunks))
        return chunks


def get_adapter(source_type: str) -> IngestionAdapter:
    """Return the appropriate adapter for the given source type."""
    adapters: dict[str, IngestionAdapter] = {
        "rss": RSSAdapter(),
        "github": GitHubAdapter(),
        "web": WebAdapter(),
        "local_folder": LocalFolderAdapter(),
    }
    adapter = adapters.get(source_type)
    if adapter is None:
        msg = f"Unsupported source type: {source_type!r}"
        raise ValueError(msg)
    return adapter
