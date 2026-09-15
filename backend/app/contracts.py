from typing import Literal
from uuid import UUID

from pydantic import BaseModel

AZURE_PROVIDERS = frozenset({"azure", "azure-cognitive-services"})


class ModelSummary(BaseModel):
    id: UUID
    provider_id: str
    provider_name: str
    model_id: str
    name: str
    context_tokens: int | None
    output_tokens: int | None
    input_price: float | None
    output_price: float | None
    reasoning: bool | None
    tool_call: bool | None
    open_weights: bool | None


SUMMARY_COLUMNS = """
    m.id, m.provider_id, p.name AS provider_name, m.model_id, m.name,
    m.context_tokens, m.output_tokens, m.input_price, m.output_price,
    m.reasoning, m.tool_call, m.open_weights
"""


class CatalogueModel(BaseModel):
    id: UUID
    model_id: str
    name: str
    publisher: str | None
    context_tokens: int | None
    output_tokens: int | None
    input_price: float | None
    output_price: float | None
    reasoning: bool | None
    tool_call: bool | None
    open_weights: bool | None
    azure_support: Literal["listed", "not_listed", "unknown"]
    pricing_provider_id: str | None


CATALOGUE_COLUMNS = """
    m.id, m.model_id, m.name, m.publisher, m.context_tokens, m.output_tokens,
    m.input_price, m.output_price, m.reasoning, m.tool_call, m.open_weights,
    m.azure_support, m.pricing_provider_id
"""
