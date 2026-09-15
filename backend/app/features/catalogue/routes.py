from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.contracts import SUMMARY_COLUMNS, ModelSummary
from app.db import read_snapshot

router = APIRouter(prefix="/api", tags=["catalogue"])


class ModelsPage(BaseModel):
    items: list[ModelSummary]
    total: int
    offset: int
    limit: int


class Provider(BaseModel):
    id: str
    name: str
    count: int


class Status(BaseModel):
    seeded_at: datetime | None = None
    model_count: int = 0
    sources: dict[str, Any] = {}


SORT_COLUMNS = {
    "name": "lower(m.name)",
    "context": "m.context_tokens",
    "input_price": "m.input_price",
    "output_price": "m.output_price",
}


@router.get("/status", response_model=Status)
def status(request: Request):
    with request.app.state.pool.connection() as connection:
        row = connection.execute(
            "SELECT seeded_at, model_count, sources FROM seed_state WHERE id = 1"
        ).fetchone()
    return row if row is not None else Status()


@router.get("/providers", response_model=list[Provider])
def providers(request: Request):
    with request.app.state.pool.connection() as connection:
        return connection.execute("""
            SELECT p.id, p.name, count(m.id) AS count
            FROM providers p JOIN models m ON m.provider_id = p.id
            GROUP BY p.id, p.name ORDER BY lower(p.name), p.id
        """).fetchall()


@router.get("/models", response_model=ModelsPage)
def models(
    request: Request,
    q: str = Query(default="", max_length=200),
    provider: str = Query(default="", max_length=200),
    reasoning: bool | None = None,
    sort: Literal["name", "context", "input_price", "output_price"] = "name",
    direction: Literal["asc", "desc"] = "asc",
    offset: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=25, ge=1, le=100),
):
    clauses: list[str] = []
    parameters: list[Any] = []
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(m.name ILIKE %s OR m.model_id ILIKE %s OR p.name ILIKE %s)")
        parameters.extend([f"%{escaped}%"] * 3)
    if provider:
        clauses.append("m.provider_id = %s")
        parameters.append(provider)
    if reasoning is not None:
        clauses.append("m.reasoning = %s")
        parameters.append(reasoning)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    joined = " FROM models m JOIN providers p ON p.id = m.provider_id"
    ordering = f"{SORT_COLUMNS[sort]} {direction} NULLS LAST, m.provider_id, m.model_id"
    with read_snapshot(request.app.state.pool) as connection:
        total = connection.execute(
            "SELECT count(*) AS total" + joined + where, parameters
        ).fetchone()["total"]
        items = connection.execute(
            f"SELECT {SUMMARY_COLUMNS}{joined}{where} ORDER BY {ordering} LIMIT %s OFFSET %s",
            [*parameters, limit, offset],
        ).fetchall()
    return {"items": items, "total": total, "offset": offset, "limit": limit}
