"""Application composition and shared infrastructure only."""

import logging
import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.db import ModelIndexNotReady, initialize_schema
from app.features.catalogue.models import router as model_catalogue_router
from app.features.catalogue.routes import router as catalogue_router
from app.features.model_details.models import router as model_detail_router
from app.features.model_details.routes import router as details_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    schema_mode = os.environ.get("CATALOGUE_INIT_SCHEMA", "true")
    if schema_mode not in {"true", "false"}:
        raise ValueError("CATALOGUE_INIT_SCHEMA must be true or false")
    with ConnectionPool(
        min_size=1, max_size=5, kwargs={"row_factory": dict_row}, open=True
    ) as pool:
        pool.wait(timeout=30)
        with pool.connection() as connection:
            if schema_mode == "true":
                initialize_schema(connection)
            else:
                connection.execute("SELECT id FROM seed_state LIMIT 1")
        app.state.pool = pool
        yield


app = FastAPI(title="Model catalogue", version="0.1.0", lifespan=lifespan)
app.include_router(catalogue_router)
app.include_router(details_router)
app.include_router(model_catalogue_router)
app.include_router(model_detail_router)


@app.exception_handler(psycopg.Error)
async def database_error(request: Request, error: psycopg.Error):
    logger.error("Database request failed: %s", request.url.path, exc_info=error)
    return JSONResponse(
        status_code=503,
        content={"detail": "The catalogue database is unavailable. Check make logs and retry."},
    )


@app.exception_handler(ModelIndexNotReady)
async def model_index_not_ready(request: Request, error: ModelIndexNotReady):
    logger.warning("Model index unavailable: %s", request.url.path)
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.get("/api/health/live")
def live():
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready(request: Request):
    with request.app.state.pool.connection() as connection:
        connection.execute("SELECT 1")
    return {"status": "ok"}
