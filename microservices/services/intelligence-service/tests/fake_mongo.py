"""A small in-memory MongoDB for route tests: the query, update and aggregation operators the lead
routes use, and unique (partial) indexes that raise DuplicateKeyError like the server.

Unsupported operators raise NotImplementedError, so a test never passes on an operator the fake ignores.
"""
import copy
import itertools
import re
from datetime import datetime
from types import SimpleNamespace

from pymongo.errors import DuplicateKeyError

_MISSING = object()
_ids = itertools.count(1)


def _get(doc, path):
    value = doc
    for part in path.split('.'):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return _MISSING
    return value


def _set(doc, path, value):
    parts = path.split('.')
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value


def _unset(doc, path):
    parts = path.split('.')
    for part in parts[:-1]:
        doc = doc.get(part)
        if not isinstance(doc, dict):
            return
    doc.pop(parts[-1], None)


def _flags(options):
    flags = 0
    for letter in options or '':
        flags |= {'i': re.IGNORECASE, 'm': re.MULTILINE, 's': re.DOTALL, 'x': re.VERBOSE}[letter]
    return flags


def _regex_match(value, pattern):
    if isinstance(value, list):
        return any(_regex_match(item, pattern) for item in value)
    return isinstance(value, str) and pattern.search(value) is not None


def _equal(value, expected):
    if expected is None:
        return value is _MISSING or value is None
    if isinstance(value, list) and not isinstance(expected, list):
        return expected in value
    return value is not _MISSING and value == expected


def _type_name(value):
    if value is _MISSING:
        return 'missing'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, int):
        return 'int'
    if isinstance(value, float):
        return 'double'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, datetime):
        return 'date'
    return 'objectId'


def _compare(value, expected, op):
    candidates = value if isinstance(value, list) else [value]
    for item in candidates:
        if item is _MISSING or item is None or expected is None:
            continue
        try:
            if op(item, expected):
                return True
        except TypeError:
            continue
    return False


def _field_matches(value, condition):
    if isinstance(condition, re.Pattern):
        return _regex_match(value, condition)
    if not (isinstance(condition, dict) and condition and all(key.startswith('$') for key in condition)):
        return _equal(value, condition)
    for op, arg in condition.items():
        if op == '$options':
            continue
        if op == '$regex':
            pattern = arg if isinstance(arg, re.Pattern) else re.compile(arg, _flags(condition.get('$options')))
            ok = _regex_match(value, pattern)
        elif op == '$eq':
            ok = _equal(value, arg)
        elif op == '$ne':
            ok = not _equal(value, arg)
        elif op == '$in':
            ok = any(_equal(value, item) for item in arg)
        elif op == '$nin':
            ok = not any(_equal(value, item) for item in arg)
        elif op == '$exists':
            ok = (value is not _MISSING) == bool(arg)
        elif op == '$type':
            ok = _type_name(value) == arg
        elif op == '$not':
            ok = not _field_matches(value, arg)
        elif op in ('$gt', '$gte', '$lt', '$lte'):
            ok = _compare(value, arg, {'$gt': lambda a, b: a > b, '$gte': lambda a, b: a >= b,
                                       '$lt': lambda a, b: a < b, '$lte': lambda a, b: a <= b}[op])
        else:
            raise NotImplementedError(f'query operator {op}')
        if not ok:
            return False
    return True


def matches(doc, query):
    for key, condition in (query or {}).items():
        if key == '$and':
            ok = all(matches(doc, item) for item in condition)
        elif key == '$or':
            ok = any(matches(doc, item) for item in condition)
        elif key == '$nor':
            ok = not any(matches(doc, item) for item in condition)
        elif key.startswith('$'):
            raise NotImplementedError(f'query operator {key}')
        else:
            ok = _field_matches(_get(doc, key), condition)
        if not ok:
            return False
    return True


def _project(doc, projection):
    doc = copy.deepcopy(doc)
    if not projection:
        return doc
    included = [name for name, flag in projection.items() if flag and name != '_id']
    if included:
        result = {name: doc[name] for name in included if name in doc}
        if projection.get('_id', 1) and '_id' in doc:
            result['_id'] = doc['_id']
        return result
    for name, flag in projection.items():
        if not flag:
            doc.pop(name, None)
    return doc


_TYPE_ORDER = {'missing': 0, 'null': 0, 'int': 1, 'double': 1, 'string': 2, 'object': 3, 'array': 4,
               'objectId': 5, 'bool': 6, 'date': 7}


def _sort_key(value):
    kind = _type_name(value)
    return (_TYPE_ORDER.get(kind, 9), None if value in (_MISSING, None) else value)


def _sort(docs, spec):
    for field, direction in reversed(spec):
        docs.sort(key=lambda doc: _sort_key(_get(doc, field)), reverse=direction < 0)
    return docs


def evaluate(expr, doc):
    if isinstance(expr, str) and expr.startswith('$'):
        return _get(doc, expr[1:])
    if isinstance(expr, list):
        return [evaluate(item, doc) for item in expr]
    if not isinstance(expr, dict):
        return expr
    if len(expr) == 1 and next(iter(expr)).startswith('$'):
        op, arg = next(iter(expr.items()))
        if op == '$literal':
            return arg
        if op in ('$toLower', '$toUpper'):
            value = evaluate(arg, doc)
            if value in (_MISSING, None):
                return ''
            return value.lower() if op == '$toLower' else value.upper()
        if op == '$trim':
            value = evaluate(arg['input'], doc)
            if not isinstance(value, str):
                raise TypeError('$trim requires its input to be a string')
            return value.strip()
        if op == '$ifNull':
            first = evaluate(arg[0], doc)
            return evaluate(arg[1], doc) if first in (_MISSING, None) else first
        if op == '$cond':
            test, then, other = (arg['if'], arg['then'], arg['else']) if isinstance(arg, dict) else arg
            return evaluate(then if evaluate(test, doc) else other, doc)
        if op == '$eq':
            left, right = (evaluate(item, doc) for item in arg)
            return (None if left is _MISSING else left) == (None if right is _MISSING else right)
        if op == '$type':
            return _type_name(evaluate(arg, doc))
        if op == '$concat':
            return ''.join(evaluate(item, doc) for item in arg)
        raise NotImplementedError(f'expression operator {op}')
    return {name: value for name, value in ((name, evaluate(item, doc)) for name, item in expr.items())
            if value is not _MISSING}


def _group(docs, spec):
    groups = {}
    order = []
    for doc in docs:
        key = evaluate(spec['_id'], doc)
        key = None if key is _MISSING else key
        marker = repr(key)
        if marker not in groups:
            groups[marker] = {'_id': key, '_docs': []}
            order.append(marker)
        groups[marker]['_docs'].append(doc)
    rows = []
    for marker in order:
        group = groups[marker]
        row = {'_id': group['_id']}
        for name, accumulator in spec.items():
            if name == '_id':
                continue
            (op, arg), = accumulator.items()
            values = [evaluate(arg, doc) for doc in group['_docs']]
            present = [value for value in values if value not in (_MISSING, None)]
            if op == '$sum':
                row[name] = sum(value for value in present if isinstance(value, (int, float)))
            elif op == '$min':
                row[name] = min(present) if present else None
            elif op == '$max':
                row[name] = max(present) if present else None
            elif op == '$first':
                row[name] = None if values[0] is _MISSING else values[0]
            elif op == '$push':
                row[name] = [value for value in values if value is not _MISSING]
            else:
                raise NotImplementedError(f'group accumulator {op}')
        rows.append(row)
    return rows


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs
        self._sort = []
        self._skip = 0
        self._limit = 0

    def sort(self, key, direction=None):
        self._sort = list(key) if isinstance(key, (list, tuple)) else [(key, direction or 1)]
        return self

    def skip(self, count):
        self._skip = count
        return self

    def limit(self, count):
        self._limit = count
        return self

    def _rows(self):
        docs = _sort(list(self._docs), self._sort) if self._sort else list(self._docs)
        docs = docs[self._skip:]
        return docs[:self._limit] if self._limit else docs

    async def to_list(self, length=None):
        rows = self._rows()
        return rows[:length] if length else rows

    def __aiter__(self):
        self._iter = iter(self._rows())
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []
        self.indexes = []

    # ------------------------------------------------------------- helpers
    def _check_unique(self, candidate, ignore=None):
        for index in self.indexes:
            if not index['unique']:
                continue
            partial = index['partial']
            if partial and not matches(candidate, partial):
                continue
            value = _get(candidate, index['field'])
            for doc in self.docs:
                if doc is ignore or (partial and not matches(doc, partial)):
                    continue
                if _get(doc, index['field']) == value:
                    raise DuplicateKeyError(f'E11000 duplicate key error collection: {self.name} '
                                            f'index: {index["field"]}_1 dup key: {value!r}')

    def _apply(self, doc, update, inserting):
        for op, fields in update.items():
            if op == '$set' or (op == '$setOnInsert' and inserting):
                for path, value in fields.items():
                    _set(doc, path, copy.deepcopy(value))
            elif op == '$setOnInsert':
                continue
            elif op == '$unset':
                for path in fields:
                    _unset(doc, path)
            elif op == '$inc':
                for path, value in fields.items():
                    current = _get(doc, path)
                    _set(doc, path, (0 if current is _MISSING else current) + value)
            elif op in ('$addToSet', '$push'):
                for path, value in fields.items():
                    items = value['$each'] if isinstance(value, dict) and '$each' in value else [value]
                    current = _get(doc, path)
                    current = [] if current is _MISSING else current
                    for item in items:
                        if op == '$push' or item not in current:
                            current.append(copy.deepcopy(item))
                    _set(doc, path, current)
            elif op in ('$max', '$min'):
                for path, value in fields.items():
                    current = _get(doc, path)
                    if current is _MISSING or (value > current if op == '$max' else value < current):
                        _set(doc, path, value)
            else:
                raise NotImplementedError(f'update operator {op}')

    # ------------------------------------------------------------- API
    async def create_index(self, keys, unique=False, partialFilterExpression=None, **kwargs):
        field = keys if isinstance(keys, str) else keys[0][0]
        index = {'field': field, 'unique': unique, 'partial': partialFilterExpression}
        if unique:
            seen = set()
            for doc in self.docs:
                if partialFilterExpression and not matches(doc, partialFilterExpression):
                    continue
                value = repr(_get(doc, field))
                if value in seen:
                    raise DuplicateKeyError(f'E11000 duplicate key error building index {field}_1')
                seen.add(value)
        self.indexes.append(index)
        return f'{field}_1'

    async def insert_one(self, doc):
        doc.setdefault('_id', next(_ids))
        stored = copy.deepcopy(doc)
        self._check_unique(stored)
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=doc['_id'])

    async def insert_many(self, docs):
        ids = [(await self.insert_one(doc)).inserted_id for doc in docs]
        return SimpleNamespace(inserted_ids=ids)

    async def find_one(self, query=None, projection=None):
        for doc in self.docs:
            if matches(doc, query):
                return _project(doc, projection)
        return None

    def find(self, query=None, projection=None):
        return FakeCursor([_project(doc, projection) for doc in self.docs if matches(doc, query)])

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if matches(doc, query))

    async def distinct(self, field, query=None):
        values = []
        for doc in self.docs:
            if not matches(doc, query):
                continue
            value = _get(doc, field)
            for item in (value if isinstance(value, list) else [value]):
                if item is not _MISSING and item not in values:
                    values.append(item)
        return values

    async def _update(self, query, update, upsert, many):
        matched = [doc for doc in self.docs if matches(doc, query)]
        if not many:
            matched = matched[:1]
        for doc in matched:
            before = copy.deepcopy(doc)
            self._apply(doc, update, inserting=False)
            try:
                self._check_unique(doc, ignore=doc)
            except DuplicateKeyError:
                doc.clear()
                doc.update(before)
                raise
        if matched or not upsert:
            return SimpleNamespace(matched_count=len(matched), modified_count=len(matched), upserted_id=None)
        doc = {name: value for name, value in query.items() if not name.startswith('$')
               and not (isinstance(value, dict) and any(key.startswith('$') for key in value))}
        self._apply(doc, update, inserting=True)
        doc.setdefault('_id', next(_ids))
        self._check_unique(doc)
        self.docs.append(doc)
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc['_id'])

    async def update_one(self, query, update, upsert=False):
        return await self._update(query, update, upsert, many=False)

    async def update_many(self, query, update, upsert=False):
        return await self._update(query, update, upsert, many=True)

    async def replace_one(self, query, replacement, upsert=False):
        for index, doc in enumerate(self.docs):
            if matches(doc, query):
                stored = copy.deepcopy(replacement)
                stored.setdefault('_id', doc['_id'])
                self._check_unique(stored, ignore=doc)
                self.docs[index] = stored
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        result = await self.insert_one(copy.deepcopy(replacement))
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=result.inserted_id)

    async def delete_one(self, query):
        for doc in self.docs:
            if matches(doc, query):
                self.docs.remove(doc)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def delete_many(self, query):
        keep = [doc for doc in self.docs if not matches(doc, query)]
        deleted = len(self.docs) - len(keep)
        self.docs = keep
        return SimpleNamespace(deleted_count=deleted)

    def aggregate(self, pipeline):
        docs = [copy.deepcopy(doc) for doc in self.docs]
        for stage in pipeline:
            (name, spec), = stage.items()
            if name == '$match':
                docs = [doc for doc in docs if matches(doc, spec)]
            elif name == '$group':
                docs = _group(docs, spec)
            elif name == '$sort':
                docs = _sort(docs, list(spec.items()))
            elif name == '$limit':
                docs = docs[:spec]
            elif name == '$skip':
                docs = docs[spec:]
            elif name == '$count':
                docs = [{spec: len(docs)}]
            else:
                raise NotImplementedError(f'aggregation stage {name}')
        return FakeCursor(docs)


class FakeDB(dict):
    def __missing__(self, name):
        collection = self[name] = FakeCollection(name)
        return collection

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]
