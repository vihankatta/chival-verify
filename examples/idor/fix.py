class DocumentStore:
    def __init__(self):
        self._docs = {}

    def add(self, doc_id, owner_id, content):
        self._docs[doc_id] = {"owner_id": owner_id, "content": content}

    def get(self, doc_id, requester_id):
        doc = self._docs.get(doc_id)
        if doc is None:
            return None
        if doc["owner_id"] != requester_id:
            return None
        return doc["content"]
