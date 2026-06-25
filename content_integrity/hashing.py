"""
Content hashing — this is the entire mechanism behind "don't re-check
unchanged blocks." We hash the *extracted plain text*, not the raw HTML,
so cosmetic edits (an added <br>, a class name change) don't trigger a
needless re-check, but an actual wording change does.
"""
import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Collapse whitespace so trivial formatting diffs don't change the hash."""
    return _WHITESPACE_RE.sub(" ", text or "").strip()


def hash_text(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
