"""uvicorn entry point: `uvicorn backend.main:app --reload --port 8000`."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.schemas.master import ProductConfig

from backend.api import public, router
from backend.graph import get_graph
from backend.settings import get_settings
from backend.store import Repository, get_store, to_doc

logger = logging.getLogger(__name__)


def seed_products(store: Repository) -> int:
    """Load data/config/products/*.json into the products collection when they are not there yet."""
    folder = get_settings().products_dir_abs
    if not folder.exists():
        return 0
    seeded = 0
    for path in sorted(folder.glob("*.json")):
        try:
            config = ProductConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("product config skipped", extra={"path": str(path), "error": str(exc)})
            continue
        if store.get(collection="products", doc_id=config.product_id) is None:
            store.upsert(collection="products", doc_id=config.product_id, doc=to_doc(config))
            seeded += 1
    return seeded


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = get_store()
    seeded = seed_products(store=store)
    get_graph()  # opens the SQLite checkpointer so paused claims are resumable immediately
    logger.info("backend ready", extra={"products_seeded": seeded})
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="LeakLens API", version="0.1.0", lifespan=lifespan,
                  description="Claims-leakage detection: ingest, checks, human review, settlement.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(public)
    app.include_router(router)
    return app


app = create_app()
