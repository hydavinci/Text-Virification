from collections import OrderedDict
from collections.abc import Callable
from math import isfinite
from threading import Lock
from time import monotonic


class ReviewLayoutCache:
    """Bounded process-local cache of validated, immutable renderer responses."""

    def __init__(
        self,
        *,
        max_bytes: int = 32 * 1024 * 1024,
        max_entries: int = 4,
        ttl_seconds: float = 60,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_bytes < 1 or max_entries < 1 or not isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("Review cache limits must be positive and finite.")
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._size = 0
        self._lock = Lock()

    def _expire(self, now: float) -> None:
        for key, (expires_at, content) in tuple(self._entries.items()):
            if expires_at <= now:
                del self._entries[key]
                self._size -= len(content)

    def get(self, key: str) -> bytes | None:
        with self._lock:
            self._expire(self._clock())
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry[1]

    def put(self, key: str, content: bytes) -> None:
        with self._lock:
            now = self._clock()
            self._expire(now)
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._size -= len(previous[1])
            if len(content) > self._max_bytes:
                return
            while self._entries and (
                self._size + len(content) > self._max_bytes
                or len(self._entries) >= self._max_entries
            ):
                _, (_, removed) = self._entries.popitem(last=False)
                self._size -= len(removed)
            self._entries[key] = (now + self._ttl_seconds, content)
            self._size += len(content)
