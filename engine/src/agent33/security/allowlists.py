"""Path and domain allow-list enforcement."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field


@dataclass
class PathAllowlist:
    """Allow-list for filesystem paths using glob patterns.

    Example::

        al = PathAllowlist(patterns=["/data/**", "/tmp/*"])
        al.is_allowed("/data/sub/file.txt")  # True
        al.is_allowed("/etc/passwd")          # False
    """

    patterns: list[str] = field(default_factory=list)

    def is_allowed(self, path: str) -> bool:
        """Return ``True`` if *path* matches any allowed pattern."""
        normalised = path.replace("\\", "/")
        return any(fnmatch.fnmatch(normalised, p.replace("\\", "/")) for p in self.patterns)


@dataclass
class DomainAllowlist:
    """Allow-list for domain names.  Supports exact match and wildcard
    prefixes (e.g. ``*.example.com``).

    Example::

        al = DomainAllowlist(domains=["api.example.com", "*.trusted.io"])
        al.is_allowed("api.example.com")    # True
        al.is_allowed("sub.trusted.io")     # True
        al.is_allowed("evil.com")           # False
    """

    domains: list[str] = field(default_factory=list)

    def is_allowed(self, domain: str) -> bool:
        """Return ``True`` if *domain* matches any allowed entry."""
        domain_lower = domain.lower()
        for pattern in self.domains:
            pattern_lower = pattern.lower()
            if pattern_lower.startswith("*."):
                suffix = pattern_lower[1:]  # e.g. ".trusted.io"
                if domain_lower == pattern_lower[2:] or domain_lower.endswith(suffix):
                    return True
            else:
                if domain_lower == pattern_lower:
                    return True
        return False
