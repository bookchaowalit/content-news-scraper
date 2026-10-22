"""Shared helpers for the feed-specific RSS/Atom adapters.

Each adapter keeps its own source policy (allowed host, feed URL, output file
names, row shape); the text cleaning, date parsing and CSV writing that used
to be copied into every adapter live here.
"""

from __future__ import annotations

import csv
import html as html_lib
import io
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone, tzinfo
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from bs4 import BeautifulSoup


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# A real tag ("<p>", "</a>", "<br/>", "<img src=...>", "<!-- -->"); a bare
# "<" in plain text ("x<y matters") is not markup.
_TAG_RE = re.compile(r"<(?:/?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*)?/?|!--.*?--)>", re.S)
# A CDATA wrapper that survived as text ("<![CDATA[...]]>" escaped twice).
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
# Invisible characters that ``\s`` does not match.
_INVISIBLE_RE = re.compile("[\u200b\u2060\ufeff\u00ad]")


def _is_cluster_continuation(char: str) -> bool:
    """True for a character that belongs to the previous grapheme.

    Combining marks (Thai tone marks and upper/lower vowels, accents),
    zero-width joiner, variation selectors and emoji skin-tone modifiers.
    """

    return (
        unicodedata.category(char) in ("Mn", "Mc", "Me")
        or char in "\u0e33\u0eb3\u200d"  # Thai/Lao sara am are SpacingMarks
        or "\ufe00" <= char <= "\ufe0f"
        or "\U0001f3fb" <= char <= "\U0001f3ff"
    )


def truncate_text(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` code points without splitting a grapheme.

    A plain slice could keep "น้" of "น้ำ" or drop a skin-tone modifier; the cut
    moves back to the start of the cluster that would be split.
    """

    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    end = limit
    while end > 0 and (_is_cluster_continuation(text[end]) or text[end - 1] == "\u200d"):
        end -= 1
    return text[:end].rstrip()


def clean_text(value: Any, limit: int) -> str:
    """Strip markup, decode entities once and collapse whitespace.

    Markup is parsed only when the value contains real tags; BeautifulSoup
    then decodes entities itself, so "&amp;lt;div&amp;gt;" stays the literal
    text "&lt;div&gt;" instead of being decoded twice. Plain text is
    unescaped once; if that reveals tags (a double-escaped summary such as
    "&lt;p&gt;Hello&lt;/p&gt;"), they are removed without decoding entities a
    second time. Leftover CDATA wrappers are unwrapped.
    """

    text = str(value or "")
    if _TAG_RE.search(text):
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    else:
        text = html_lib.unescape(text)
        if _TAG_RE.search(text):
            text = _TAG_RE.sub(" ", text)
    text = _CDATA_RE.sub(r" \1 ", text)
    text = _INVISIBLE_RE.sub("", text)
    return truncate_text(re.sub(r"\s+", " ", text).strip(), limit)


def _raw(entry: Any, key: str) -> Any:
    """Read ``key`` without feedparser's ``updated`` -> ``published`` fallback.

    ``FeedParserDict`` maps a missing ``updated`` to ``published`` with a
    DeprecationWarning; that silently made ``updated_at`` equal
    ``published_at``. ``in`` checks the real key only.
    """

    if key in ("updated", "updated_parsed"):
        return entry[key] if key in entry else None
    return entry.get(key)


def parse_timestamp(value: Any, default_tz: tzinfo = timezone.utc) -> str:
    """Return an ISO-8601 UTC ``...Z`` string, or ``""`` when unparseable."""

    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def published_at(entry: Any, default_tz: tzinfo = timezone.utc) -> str:
    """First parseable of ``published``/``updated``/``created``."""

    for key in ("published", "updated", "created"):
        value = parse_timestamp(_raw(entry, key), default_tz)
        if value:
            return value
    return ""


def updated_at(entry: Any, default_tz: tzinfo = timezone.utc) -> str:
    """The entry's own ``updated`` time only; ``""`` when the feed has none."""

    return parse_timestamp(_raw(entry, "updated"), default_tz)


def image_url(entry: Any) -> str:
    for key in ("media_content", "media_thumbnail", "enclosures"):
        values = entry.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, dict) and value.get("url"):
                return str(value["url"]).strip()
    return ""


def tag_terms(entry: Any, limit: int = 10) -> str:
    """Comma-joined, de-duplicated tag terms (at most ``limit``)."""

    values = entry.get("tags")
    if not isinstance(values, list):
        return ""
    terms: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        term = clean_text(value.get("term"), 80)
        if term and term not in terms:
            terms.append(term)
    return ",".join(terms[:limit])


def _replace_atomic(path: Path, data: bytes) -> Path:
    """Write ``data`` to a temp file beside ``path``, fsync, then ``os.replace`` it.

    The parent control plane replays these files into Bronze; readers must see the
    previous capture or the new one, never a truncated file.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def write_bytes(raw: bytes, path: Path) -> Path:
    return _replace_atomic(path, raw)


def write_snapshot(path: Path, fields: list[str], rows: Iterable[Mapping[str, Any]], captured_at: str) -> Path:
    # Render fully in memory first: a failing row must not touch the existing file.
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "captured_at": captured_at})
    return _replace_atomic(path, buffer.getvalue().encode("utf-8"))


def append_history(path: Path, fields: list[str], rows: Iterable[Mapping[str, Any]], captured_at: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({**row, "captured_at": captured_at})
    return path
