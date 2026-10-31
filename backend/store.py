"""The repository: one interface, two implementations chosen at startup.

- `MongoStore` (pymongo + GridFS for document bytes) when MONGODB_URI is set.
- `JsonFileStore` (one JSON file per collection, document bytes as files) otherwise, so a demo needs no database.

Every document is a JSON-safe dict keyed by its natural id (claim_id, finding_id, ...). `list` takes a flat
equality filter ({"claim_id": "CLM-1"}); anything richer is done in Python by the caller.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import time
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from backend.settings import get_settings

logger = logging.getLogger(__name__)

COLLECTIONS = ["products", "policies", "claims", "invoice_lines", "history", "documents", "master_records",
               "findings", "settlements", "reviews", "audit", "runs", "batches"]

Doc = Dict[str, Any]


def to_doc(model: BaseModel) -> Doc:
    """Pydantic model -> JSON-safe dict (dates and enums become strings) so both stores behave the same."""
    return model.model_dump(mode="json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matches(doc: Doc, filter_: Optional[Doc]) -> bool:
    if not filter_:
        return True
    return all(doc.get(key) == value for key, value in filter_.items())


class Repository(ABC):
    """The six methods every store implements."""

    @abstractmethod
    def upsert(self, collection: str, doc_id: str, doc: Doc) -> Doc: ...

    @abstractmethod
    def get(self, collection: str, doc_id: str) -> Optional[Doc]: ...

    @abstractmethod
    def list(self, collection: str, filter_: Optional[Doc] = None) -> List[Doc]: ...

    @abstractmethod
    def delete(self, collection: str, doc_id: str) -> bool: ...

    @abstractmethod
    def save_document(self, data: bytes, name: str, mime: str) -> str: ...

    @abstractmethod
    def open_document(self, document_id: str) -> Tuple[bytes, str, str]: ...

    def bulk_upsert(self, collection: str, docs: Dict[str, Doc]) -> int:
        """Upsert many documents ({id: doc}) in one write; stores override this for speed."""
        for doc_id, doc in docs.items():
            self.upsert(collection=collection, doc_id=doc_id, doc=doc)
        return len(docs)

    def delete_where(self, collection: str, filter_: Doc, id_field: str) -> int:
        """Delete every document matching the filter; returns the count."""
        removed = 0
        for doc in self.list(collection=collection, filter_=filter_):
            if self.delete(collection=collection, doc_id=str(doc[id_field])):
                removed += 1
        return removed


class JsonFileStore(Repository):
    """DATA_DIR/<collection>.json holding {id: doc}; document bytes under DATA_DIR/documents/."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files_dir = root / "documents"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cache: Dict[str, Dict[str, Doc]] = {}

    def _path(self, collection: str) -> Path:
        return self.root / f"{collection}.json"

    def _load(self, collection: str) -> Dict[str, Doc]:
        if collection not in self._cache:
            path = self._path(collection)
            self._cache[collection] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return self._cache[collection]

    def _flush(self, collection: str) -> None:
        path = self._path(collection)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._cache[collection], ensure_ascii=False, indent=1), encoding="utf-8")
        # Windows: a reader (or a virus scanner) can hold the target for a moment; retry the swap briefly.
        for attempt in range(40):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, path)

    def upsert(self, collection: str, doc_id: str, doc: Doc) -> Doc:
        with self._lock:
            data = self._load(collection)
            data[doc_id] = doc
            self._flush(collection)
        return doc

    def bulk_upsert(self, collection: str, docs: Dict[str, Doc]) -> int:
        if not docs:
            return 0
        with self._lock:
            self._load(collection).update(docs)
            self._flush(collection)
        return len(docs)

    def get(self, collection: str, doc_id: str) -> Optional[Doc]:
        with self._lock:
            return self._load(collection).get(doc_id)

    def list(self, collection: str, filter_: Optional[Doc] = None) -> List[Doc]:
        with self._lock:
            return [doc for doc in self._load(collection).values() if _matches(doc, filter_)]

    def delete(self, collection: str, doc_id: str) -> bool:
        with self._lock:
            data = self._load(collection)
            if doc_id not in data:
                return False
            del data[doc_id]
            self._flush(collection)
            return True

    def save_document(self, data: bytes, name: str, mime: str) -> str:
        document_id = uuid.uuid4().hex
        suffix = Path(name).suffix.lower() or (mimetypes.guess_extension(mime) or ".bin")
        file_path = self.files_dir / f"{document_id}{suffix}"
        file_path.write_bytes(data)
        self.upsert(collection="documents", doc_id=document_id,
                    doc={"document_id": document_id, "name": name, "mime": mime, "size": len(data),
                         "path": str(file_path), "uploaded_at": now_iso()})
        return document_id

    def open_document(self, document_id: str) -> Tuple[bytes, str, str]:
        meta = self.get(collection="documents", doc_id=document_id)
        if meta is None:
            raise KeyError(document_id)
        return Path(meta["path"]).read_bytes(), meta["name"], meta["mime"]


class MongoStore(Repository):
    """MongoDB collections keyed by `_id`; document bytes in GridFS."""

    def __init__(self, uri: str, db_name: str) -> None:
        from gridfs import GridFS
        from pymongo import MongoClient

        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[db_name]
        self.fs = GridFS(self.db)

    def upsert(self, collection: str, doc_id: str, doc: Doc) -> Doc:
        self.db[collection].replace_one({"_id": doc_id}, {**doc, "_id": doc_id}, upsert=True)
        return doc

    def bulk_upsert(self, collection: str, docs: Dict[str, Doc]) -> int:
        from pymongo import ReplaceOne

        if not docs:
            return 0
        self.db[collection].bulk_write([ReplaceOne({"_id": doc_id}, {**doc, "_id": doc_id}, upsert=True)
                                        for doc_id, doc in docs.items()], ordered=False)
        return len(docs)

    def get(self, collection: str, doc_id: str) -> Optional[Doc]:
        return self.db[collection].find_one({"_id": doc_id}, {"_id": 0})

    def list(self, collection: str, filter_: Optional[Doc] = None) -> List[Doc]:
        return list(self.db[collection].find(filter_ or {}, {"_id": 0}))

    def delete(self, collection: str, doc_id: str) -> bool:
        return self.db[collection].delete_one({"_id": doc_id}).deleted_count == 1

    def save_document(self, data: bytes, name: str, mime: str) -> str:
        file_id = self.fs.put(data, filename=name, content_type=mime)
        document_id = str(file_id)
        self.upsert(collection="documents", doc_id=document_id,
                    doc={"document_id": document_id, "name": name, "mime": mime, "size": len(data),
                         "gridfs_id": document_id, "uploaded_at": now_iso()})
        return document_id

    def open_document(self, document_id: str) -> Tuple[bytes, str, str]:
        from bson import ObjectId

        meta = self.get(collection="documents", doc_id=document_id)
        if meta is None:
            raise KeyError(document_id)
        grid_out = self.fs.get(ObjectId(meta["gridfs_id"]))
        return grid_out.read(), meta["name"], meta["mime"]


_store: Optional[Repository] = None
_store_lock = threading.Lock()


def get_store() -> Repository:
    """The process-wide repository, built on first use from the settings."""
    global _store
    with _store_lock:
        if _store is None:
            settings = get_settings()
            if settings.mongodb_uri:
                _store = MongoStore(uri=settings.mongodb_uri, db_name=settings.mongodb_db)
                logger.info("store: mongodb", extra={"db": settings.mongodb_db})
            else:
                _store = JsonFileStore(root=settings.data_dir_abs)
                logger.info("store: json files", extra={"root": str(settings.data_dir_abs)})
        return _store


def reset_store() -> None:
    """Forget the current store (tests point DATA_DIR at a fresh directory)."""
    global _store
    with _store_lock:
        _store = None
