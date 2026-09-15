from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.contracts import CATALOGUE_COLUMNS, CatalogueModel
from app.db import read_snapshot, require_model_index

router = APIRouter(prefix="/api/catalogue", tags=["model catalogue"])


class CatalogueStatus(BaseModel):
    seeded_at: datetime | None = None
    model_count: int = 0
    offering_count: int = 0
    sources: dict[str, Any] = {}


class CataloguePage(BaseModel):
    items: list[CatalogueModel]
    total: int
    offset: int
    limit: int


@router.get("/status", response_model=CatalogueStatus)
def status(request: Request):
    with read_snapshot(request.app.state.pool) as connection:
        require_model_index(connection)
        row = connection.execute(
            """SELECT seeded_at, catalogue_count AS model_count,
                      model_count AS offering_count, sources FROM seed_state WHERE id=1"""
        ).fetchone()
    return row if row is not None else CatalogueStatus()


@router.get("/models", response_model=CataloguePage)
def models(
    request: Request,
    q: str = Query(default="", max_length=200),
    azure: Literal["listed", "not_listed", "unknown"] | None = None,
    reasoning: bool | None = None,
    sort: Literal["name", "context", "input_price", "output_price"] = "name",
    direction: Literal["asc", "desc"] = "asc",
    offset: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=25, ge=1, le=100),
):
    clauses, parameters = [], []
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(m.name ILIKE %s OR m.model_id ILIKE %s OR m.publisher ILIKE %s)")
        parameters.extend([f"%{escaped}%"] * 3)
    if azure is not None:
        clauses.append("m.azure_support=%s")
        parameters.append(azure)
    if reasoning is not None:
        clauses.append("m.reasoning=%s")
        parameters.append(reasoning)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    column = {
        "name": "lower(m.name)",
        "context": "m.context_tokens",
        "input_price": "m.input_price",
        "output_price": "m.output_price",
    }[sort]
    with read_snapshot(request.app.state.pool) as connection:
        require_model_index(connection)
        total = connection.execute(
            "SELECT count(*) AS total FROM catalogue_models m" + where, parameters
        ).fetchone()["total"]
        items = connection.execute(
            f"SELECT {CATALOGUE_COLUMNS} FROM catalogue_models m{where} "
            f"ORDER BY {column} {direction} NULLS LAST, m.model_id LIMIT %s OFFSET %s",
            [*parameters, limit, offset],
        ).fetchall()
    return {"items": items, "total": total, "offset": offset, "limit": limit}
