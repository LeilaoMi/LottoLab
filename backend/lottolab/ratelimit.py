"""In-process per-IP rate limiting for POST endpoints (defense in depth).

Cloudflare /reverse-proxy limits stay primary; this guard also protects
self-hosted deployments. State is per process: on serverless platforms each
instance keeps its own budget, so treat this as a backstop, not a quota.

X-Forwarded-For is only trusted when the TCP peer is a trusted proxy
(loopback / private / LOTTOLAB_TRUSTED_PROXIES). Direct clients cannot
rotate a spoofed XFF to bypass the limiter.
"""

import ipaddress
import time
from collections import deque
from threading import Lock

from fastapi import Request


class PostRateLimiter:
    """Sliding-window counter per client key using a monotonic clock."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allowed(self, key: str, now: float | None = None) -> bool:
        if self.per_minute <= 0:
            return True
        moment = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= moment - 60.0:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False
            hits.append(moment)
            if len(self._hits) > 10000:
                self._hits = {k: v for k, v in self._hits.items() if v}
            return True


def _is_proxy_hop(ip: str, trusted: list[str]) -> bool:
    if ip in trusted:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def client_ip(request: Request, trusted_proxies: list[str] | None = None) -> str:
    """Client key: peer address, or rightmost untrusted XFF hop if peer is a trusted proxy.

    When every XFF hop is itself a trusted proxy (private LAN client behind
    reverse proxies), prefer the rightmost entry — the hop appended by the
    nearest proxy — so a client cannot rotate a leftmost spoofed value.
    """
    peer = request.client.host if request.client else "unknown"
    trusted = trusted_proxies or []
    if not _is_proxy_hop(peer, trusted):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    for ip in reversed(parts):
        if not _is_proxy_hop(ip, trusted):
            return ip
    if parts:
        return parts[-1]
    return peer
