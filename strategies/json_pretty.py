import json
from typing import Any


def serialize(tools: list[dict[str, Any]]) -> str:
    return json.dumps({"tools": tools}, indent=2, ensure_ascii=False)
