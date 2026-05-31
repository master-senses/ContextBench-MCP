"""Run tool-selection evals: fixture + encoding strategy + prompt → model pick → score."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import litellm
import yaml
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

STRATEGIES = {
    "json_pretty": lambda tools: json.dumps({"tools": tools}, indent=2, ensure_ascii=False),
    "json_minified": lambda tools: json.dumps({"tools": tools}, separators=(",", ":"), ensure_ascii=False),
}

SYSTEM_TEMPLATE = """You are a tool-selection benchmark agent.

You are given MCP tool definitions below. Pick exactly ONE tool that best matches the user request.
Do not invent tools. Do not call tools.

## Available tools

{schema}
"""


class ToolPick(BaseModel):
    tool_name: str


@dataclass
class PromptCase:
    id: str
    prompt: str
    gold_tool: str
    acceptable_alternatives: list[str]


@dataclass
class SelectionResult:
    case_id: str
    strategy: str
    model: str
    gold_tool: str
    predicted_tool: str | None
    correct: bool
    schema_chars: int
    prompt_tokens: int | None
    completion_tokens: int | None
    raw_response: str


def pick_tool(
    *,
    model: str,
    strategy: str,
    tools: list[dict[str, Any]],
    case: PromptCase,
    temperature: float,
) -> SelectionResult:
    schema_text = STRATEGIES[strategy](tools)
    known_tools = {t["name"] for t in tools}

    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_TEMPLATE.format(schema=schema_text)},
            {"role": "user", "content": f"User request: {case.prompt}"},
        ],
        response_format=ToolPick,
        temperature=temperature,
        max_tokens=64,
    )

    raw = (response.choices[0].message.content or "").strip()
    try:
        predicted = ToolPick.model_validate_json(raw).tool_name
    except ValidationError:
        predicted = None

    if predicted not in known_tools:
        predicted = None

    usage = response.usage
    allowed = {case.gold_tool, *case.acceptable_alternatives}
    return SelectionResult(
        case_id=case.id,
        strategy=strategy,
        model=model,
        gold_tool=case.gold_tool,
        predicted_tool=predicted,
        correct=predicted is not None and predicted in allowed,
        schema_chars=len(schema_text),
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        raw_response=raw,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run tool-selection eval via LiteLLM")
    parser.add_argument("--fixture", default="filesystem")
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default="json_minified")
    parser.add_argument("--model", default=os.environ.get("CONTEXTBENCH_MODEL", DEFAULT_MODEL))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required for Anthropic models via LiteLLM")

    fixture_path = ROOT / "fixtures" / f"{args.fixture}.json"
    prompt_path = ROOT / "prompts" / f"{args.fixture}.yaml"
    tools = json.loads(fixture_path.read_text(encoding="utf-8"))["tools"]
    cases = [
        PromptCase(
            id=row["id"],
            prompt=row["prompt"],
            gold_tool=row["gold_tool"],
            acceptable_alternatives=list(row.get("acceptable_alternatives") or []),
        )
        for row in yaml.safe_load(prompt_path.read_text(encoding="utf-8"))["prompts"]
    ]

    results = [
        pick_tool(
            model=args.model,
            strategy=args.strategy,
            tools=tools,
            case=case,
            temperature=args.temperature,
        )
        for case in cases
    ]

    correct = sum(r.correct for r in results)
    summary = {
        "total": len(results),
        "correct": correct,
        "pass_at_1": round(correct / len(results), 4) if results else 0.0,
        "strategy": args.strategy,
        "model": args.model,
        "schema_chars": results[0].schema_chars if results else 0,
    }

    out_path = args.output or ROOT / "results" / f"{args.fixture}-{args.strategy}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
