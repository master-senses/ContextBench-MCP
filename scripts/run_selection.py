"""Run tool-selection evals: fixture + tool presentation + prompt -> model pick -> score."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import litellm
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

# Simulate how MCP tool definitions arrive from tools/list before the host maps them
# to the provider tools API. Both paths end as structured objects -> tools=.
TOOL_SERIALIZERS = {
    "json_pretty": lambda tools: json.loads(json.dumps(tools, indent=2, ensure_ascii=False)),
    "json_minified": lambda tools: json.loads(json.dumps(tools, separators=(",", ":"), ensure_ascii=False)),
}
STRATEGY_CHOICES = sorted(TOOL_SERIALIZERS)

CACHE_CONTROL: dict[str, str] = {"type": "ephemeral"}
SYSTEM_PROMPT = (
    "You are a tool-selection benchmark agent. Choose exactly one available tool that best "
    "matches the user request. Call that tool once. Do not answer in text."
)


def wire_chars(tools: list[dict[str, Any]], strategy: str) -> int:
    if strategy == "json_minified":
        payload = json.dumps({"tools": tools}, separators=(",", ":"), ensure_ascii=False)
    else:
        payload = json.dumps({"tools": tools}, indent=2, ensure_ascii=False)
    return len(payload)


def to_provider_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    native_tools = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description") or tool.get("title") or tool["name"],
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]
    if native_tools:
        native_tools[-1]["function"]["cache_control"] = CACHE_CONTROL
    return native_tools


def usage_value(usage: Any, key: str) -> int | None:
    return (usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)) if usage else None


def pick_tool(
    *,
    model: str,
    provider_tools: list[dict[str, Any]],
    known_tools: set[str],
    case: dict[str, Any],
    schema_chars: int,
    strategy: str,
    temperature: float,
) -> dict[str, Any]:
    response = litellm.completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": CACHE_CONTROL}],
            },
            {"role": "user", "content": case["prompt"]},
        ],
        tools=provider_tools,
        tool_choice="required",
        temperature=temperature,
        max_tokens=256,
    )

    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None) or []
    function = getattr(tool_calls[0], "function", None) if tool_calls else None
    if tool_calls and isinstance(tool_calls[0], dict):
        function = tool_calls[0].get("function")
    predicted = function.get("name") if isinstance(function, dict) else getattr(function, "name", None)
    if predicted not in known_tools:
        predicted = None

    usage = response.usage
    allowed = {case["gold_tool"], *list(case.get("acceptable_alternatives") or [])}
    return {
        "case_id": case["id"],
        "strategy": strategy,
        "model": model,
        "gold_tool": case["gold_tool"],
        "predicted_tool": predicted,
        "correct": predicted is not None and predicted in allowed,
        "schema_chars": schema_chars,
        "prompt_tokens": usage_value(usage, "prompt_tokens"),
        "completion_tokens": usage_value(usage, "completion_tokens"),
        "cache_read_tokens": usage_value(usage, "cache_read_input_tokens"),
        "cache_write_tokens": usage_value(usage, "cache_creation_input_tokens"),
        "raw_response": json.dumps(
            {"content": getattr(message, "content", None), "tool_calls": tool_calls},
            default=str,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run tool-selection eval via LiteLLM")
    parser.add_argument("--fixture", default="filesystem")
    parser.add_argument("--strategy", choices=STRATEGY_CHOICES, default="json_pretty")
    parser.add_argument("--model", default=os.environ.get("CONTEXTBENCH_MODEL", DEFAULT_MODEL))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required for Anthropic models via LiteLLM")

    fixture_path = ROOT / "fixtures" / f"{args.fixture}.json"
    prompt_path = ROOT / "prompts" / f"{args.fixture}.yaml"
    raw_tools = json.loads(fixture_path.read_text(encoding="utf-8"))["tools"]
    mcp_tools = TOOL_SERIALIZERS[args.strategy](raw_tools)
    provider_tools = to_provider_tools(mcp_tools)
    known_tools = {t["name"] for t in mcp_tools}
    schema_chars = wire_chars(mcp_tools, args.strategy)
    cases = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))["prompts"]

    results = [
        pick_tool(
            model=args.model,
            provider_tools=provider_tools,
            known_tools=known_tools,
            case=case,
            schema_chars=schema_chars,
            strategy=args.strategy,
            temperature=args.temperature,
        )
        for case in cases
    ]

    correct = sum(r["correct"] for r in results)
    summary = {
        "total": len(results),
        "correct": correct,
        "pass_at_1": round(correct / len(results), 4) if results else 0.0,
        "strategy": args.strategy,
        "model": args.model,
        "schema_chars": schema_chars,
        "cache_write_tokens": sum(r["cache_write_tokens"] or 0 for r in results),
        "cache_read_tokens": sum(r["cache_read_tokens"] or 0 for r in results),
    }

    out_path = args.output or ROOT / "results" / f"{args.fixture}-{args.strategy}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
