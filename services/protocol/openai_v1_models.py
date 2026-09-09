from __future__ import annotations

from typing import Any

from services.model_catalog_service import get_model_catalog


def _model_item(model: str) -> dict[str, Any]:
    return {
        "id": model,
        "object": "model",
        "created": 0,
        "owned_by": "chatgpt2api",
        "permission": [],
        "root": model,
        "parent": None,
    }


def list_models() -> dict[str, Any]:
    catalog = get_model_catalog()
    return {"object": "list", "data": [_model_item(model) for model in catalog.all_models]}
