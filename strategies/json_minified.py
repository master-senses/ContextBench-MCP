import json
from typing import Any


def serialize(tools: list[dict[str, Any]]) -> str:
    return json.dumps({"tools": tools}, separators=(",", ":"), ensure_ascii=False)
