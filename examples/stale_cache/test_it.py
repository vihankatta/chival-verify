from solution import Cache


def test_invalidate_prefix_removes_matching_keys():
    c = Cache()
    c.set("user:1", "alice")
    c.set("user:2", "bob")
    c.set("order:1", "widget")
    c.invalidate_prefix("user:")
    assert c.get("user:1") is None
    assert c.get("user:2") is None
    assert c.get("order:1") == "widget"


def test_invalidate_prefix_with_no_matches_is_a_noop():
    c = Cache()
    c.set("order:1", "widget")
    c.invalidate_prefix("user:")
    assert c.get("order:1") == "widget"
