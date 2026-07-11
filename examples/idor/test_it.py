from solution import DocumentStore


def test_owner_can_read_their_document():
    store = DocumentStore()
    store.add("doc-1", owner_id="alice", content="secret plans")
    assert store.get("doc-1", requester_id="alice") == "secret plans"


def test_non_owner_cannot_read_document():
    store = DocumentStore()
    store.add("doc-1", owner_id="alice", content="secret plans")
    assert store.get("doc-1", requester_id="mallory") is None
