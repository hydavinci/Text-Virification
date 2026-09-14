from text_verification.application.review_layout_cache import ReviewLayoutCache


def test_cache_expires_entries_and_promotes_recently_used_layouts() -> None:
    now = [0.0]
    cache = ReviewLayoutCache(
        max_bytes=100, max_entries=2, ttl_seconds=10, clock=lambda: now[0],
    )
    cache.put("first", b"aaa")
    cache.put("second", b"bbb")
    assert cache.get("first") == b"aaa"
    now[0] = 5
    cache.put("third", b"ccc")
    assert cache.get("second") is None
    assert cache.get("first") == b"aaa"
    assert cache.get("third") == b"ccc"
    now[0] = 10
    assert cache.get("first") is None
    assert cache.get("third") == b"ccc"
    now[0] = 15
    assert cache.get("third") is None


def test_cache_bounds_bytes_and_does_not_keep_oversized_results() -> None:
    cache = ReviewLayoutCache(max_bytes=6, max_entries=4)
    cache.put("first", b"aaaa")
    cache.put("second", b"bbb")
    assert cache.get("first") is None
    assert cache.get("second") == b"bbb"
    cache.put("oversized", b"1234567")
    assert cache.get("oversized") is None
    assert cache.get("second") == b"bbb"
    cache.put("second", b"cccccc")
    assert cache.get("second") == b"cccccc"
