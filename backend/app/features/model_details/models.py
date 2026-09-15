from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.contracts import CATALOGUE_COLUMNS, CatalogueModel
from app.db import read_snapshot, require_model_index

router = APIRouter(prefix="/api/catalogue", tags=["model catalogue details"])


class CatalogueModelDetail(CatalogueModel):
    raw: dict[str, Any]
    metadata: dict[str, Any] | None
    providers: list[dict[str, Any]]
    azure: list[dict[str, Any]]
    azure_source: dict[str, Any]


@router.get("/models/{model_id}", response_model=CatalogueModelDetail)
def model_detail(model_id: UUID, request: Request):
    with read_snapshot(request.app.state.pool) as connection:
        require_model_index(connection)
        target = connection.execute(
            """SELECT target_id FROM catalogue_model_redirects WHERE source_id=%s
               UNION ALL SELECT catalogue_id FROM models WHERE id=%s AND catalogue_id IS NOT NULL
               LIMIT 1""",
            [model_id, model_id],
        ).fetchone()
        resolved = target["target_id"] if target else model_id
        model = connection.execute(
            f"SELECT {CATALOGUE_COLUMNS}, m.raw, m.metadata "
            "FROM catalogue_models m WHERE m.id=%s",
            [resolved],
        ).fetchone()
        if model is None:
            raise HTTPException(
                404, "This model is not identified in the current catalogue snapshot."
            )
        model["providers"] = connection.execute(
            """SELECT o.id, o.provider_id, p.name AS provider_name, o.model_id, o.name,
                      o.context_tokens, o.output_tokens, o.input_price, o.output_price,
                      o.metadata_match, o.raw
               FROM models o JOIN providers p ON p.id=o.provider_id
               WHERE o.catalogue_id=%s ORDER BY p.name, o.model_id""",
            [model["id"]],
        ).fetchall()
        model["azure"] = connection.execute(
            """SELECT a.location,a.model_name,a.version,a.raw FROM catalogue_models m
               CROSS JOIN LATERAL jsonb_to_recordset(m.azure_observations)
                   AS matched(model_name text,version text)
               JOIN azure_models a
                   ON a.model_name=matched.model_name AND a.version=matched.version
               WHERE m.id=%s ORDER BY a.location,a.model_name,a.version""",
            [model["id"]],
        ).fetchall()
        state = connection.execute("SELECT sources FROM seed_state WHERE id=1").fetchone()
        model["azure_source"] = (
            state["sources"].get("azure", {"status": "not_configured"})
            if state
            else {"status": "not_configured"}
        )
    return model
