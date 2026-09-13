from copy import deepcopy
from types import SimpleNamespace


def matches(doc, query):
    for key, wanted in query.items():
        if key == '$or':
            if not any(matches(doc, item) for item in wanted):
                return False
        elif key == '$and':
            if not all(matches(doc, item) for item in wanted):
                return False
        elif isinstance(wanted, dict):
            value = doc.get(key)
            for op, operand in wanted.items():
                if op == '$exists' and (key in doc) != operand:
                    return False
                if op == '$lte' and (value is None or value > operand):
                    return False
        elif doc.get(key) != wanted:
            return False
    return True


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def limit(self, size):
        self.docs = self.docs[:size]
        return self

    def __aiter__(self):
        async def iterate():
            for doc in self.docs:
                yield deepcopy(doc)
        return iterate()


class PackageStore:
    def __init__(self):
        self.docs = {}

    async def find_one(self, query, *args, **kwargs):
        return next((deepcopy(d) for d in self.docs.values() if matches(d, query)), None)

    def find(self, query):
        return Cursor([d for d in self.docs.values() if matches(d, query)])

    async def update_one(self, query, update, upsert=False):
        doc = next((d for d in self.docs.values() if matches(d, query)), None)
        inserted = doc is None and upsert
        if inserted:
            doc = deepcopy(update.get('$setOnInsert', {}))
            self.docs[doc['_id']] = doc
        if doc is None:
            return SimpleNamespace(modified_count=0)
        old = deepcopy(doc)
        doc.update(deepcopy(update.get('$set', {})))
        for key, value in update.get('$inc', {}).items():
            doc[key] = doc.get(key, 0) + value
        for key in update.get('$unset', {}):
            doc.pop(key, None)
        return SimpleNamespace(modified_count=int(inserted or old != doc))

    async def delete_one(self, query):
        doc = await self.find_one(query)
        if doc:
            del self.docs[doc['_id']]
        return SimpleNamespace(deleted_count=int(doc is not None))

    async def update_many(self, query, update):
        ids = [doc['_id'] for doc in self.docs.values() if matches(doc, query)]
        for key in ids:
            await self.update_one({'_id': key}, update)
        return SimpleNamespace(modified_count=len(ids))
