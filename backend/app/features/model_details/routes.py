from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.contracts import AZURE_PROVIDERS, SUMMARY_COLUMNS, ModelSummary
from app.db import read_snapshot

router = APIRouter(prefix="/api", tags=["model details"])


class ModelDetail(ModelSummary):
    metadata_id: str | None
    metadata_match: str | None
    raw: dict[str, Any]
    metadata: dict[str, Any] | None
    azure: list[dict[str, Any]]
    azure_source: dict[str, Any]


@router.get("/models/{model_id}", response_model=ModelDetail)
def model_detail(model_id: UUID, request: Request):
    with read_snapshot(request.app.state.pool) as connection:
        model = connection.execute(
            f"""SELECT {SUMMARY_COLUMNS}, m.metadata_id, m.metadata_match, m.raw, m.metadata
                FROM models m JOIN providers p ON p.id = m.provider_id WHERE m.id = %s""",
            [model_id],
        ).fetchone()
        if model is None:
            raise HTTPException(
                status_code=404, detail="This model is not in the current snapshot."
            )
        model["azure"] = []
        state = connection.execute("SELECT sources FROM seed_state WHERE id = 1").fetchone()
        model["azure_source"] = (
            state["sources"].get("azure", {"status": "not_configured"})
            if state
            else {"status": "not_configured"}
        )
        if model["provider_id"] in AZURE_PROVIDERS:
            model["azure"] = connection.execute(
                """SELECT location, model_name, version, raw FROM azure_models
                   WHERE model_name = %s ORDER BY location, version""",
                [model["model_id"]],
            ).fetchall()
    return model
