"""URL normalization, templating (/patients/12 ≈ /patients/13) and crawl scope."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urldefrag, urlencode, urlparse, urlunparse

_NUMERIC = re.compile(r"^\d+$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HEX = re.compile(r"^[0-9a-f]{16,}$", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLUG_WITH_ID = re.compile(r"^(?:[a-z0-9]+-)+\d+$", re.I)  # e.g. blue-shirt-1234


def normalize(url: str, ignore_params: list[str] | tuple[str, ...] = ()) -> str:
    """Drop fragments and tracking params, sort the query, lowercase scheme/host, strip default ports."""
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    scheme = p.scheme.lower()
    host = (p.hostname or "").lower()
    port = p.port
    netloc = host if not port or (scheme, port) in (("http", 80), ("https", 443)) else f"{host}:{port}"
    ignore = {i.lower() for i in ignore_params}
    query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in ignore)
    # Trailing slashes are kept: many servers treat /docs and /docs/ as different resources.
    path = p.path or "/"
    return urlunparse((scheme, netloc, path, "", urlencode(query), ""))


def _segment_template(seg: str) -> str:
    if _NUMERIC.match(seg):
        return "{id}"
    if _UUID.match(seg):
        return "{uuid}"
    if _HEX.match(seg):
        return "{hash}"
    if _DATE.match(seg):
        return "{date}"
    if _SLUG_WITH_ID.match(seg):
        return "{slug}"
    return seg


def template(url: str) -> str:
    """Pattern used to group pages that are the same screen with different records."""
    p = urlparse(url)
    path = "/".join(_segment_template(s) for s in p.path.split("/"))
    query = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        query.append(f"{k}={_segment_template(v) if v else ''}")
    q = ("?" + "&".join(sorted(query))) if query else ""
    return f"{path or '/'}{q}"


class Scope:
    def __init__(
        self, start_url: str, include: list[str] | None = None, exclude: list[str] | None = None
    ) -> None:
        p = urlparse(start_url)
        self.host = (p.hostname or "").lower()
        self.scheme = p.scheme
        self.include = [re.compile(x, re.I) for x in include or []]
        self.exclude = [re.compile(x, re.I) for x in exclude or []]

    def allows(self, url: str) -> bool:
        for pattern in self.exclude:
            if pattern.search(url):
                return False
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        host = (p.hostname or "").lower()
        same_site = host == self.host or host.endswith("." + self.host) or self.host.endswith("." + host)
        if not same_site:
            return False
        if self.include:
            return any(pattern.search(url) for pattern in self.include)
        return True
