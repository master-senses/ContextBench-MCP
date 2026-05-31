"""Run tool-selection evals: fixture + encoding strategy + prompt → model pick → score."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import litellm
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "fixtures"
PROMPTS_DIR = ROOT / "prompts"
RESULTS_DIR = ROOT / "results"

# Swap when Anthropic ships a newer Sonnet; LiteLLM uses provider/model id.
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

Serializer = Callable[[list[dict[str, Any]]], str]


def serialize_json_pretty(tools: list[dict[str, Any]]) -> str:
    return json.dumps({"tools": tools}, indent=2, ensure_ascii=False)


def serialize_json_minified(tools: list[dict[str, Any]]) -> str:
    return json.dumps({"tools": tools}, separators=(",", ":"), ensure_ascii=False)


STRATEGIES: dict[str, Serializer] = {
    "json_pretty": serialize_json_pretty,
    "json_minified": serialize_json_minified,
}


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


def load_fixture(name: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["tools"]


def load_prompts(name: str) -> list[PromptCase]:
    path = PROMPTS_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases: list[PromptCase] = []
    for row in data["prompts"]:
        cases.append(
            PromptCase(
                id=row["id"],
                prompt=row["prompt"],
                gold_tool=row["gold_tool"],
                acceptable_alternatives=list(row.get("acceptable_alternatives") or []),
            )
        )
    return cases


def build_system_prompt(schema_text: str) -> str:
    return f"""You are a tool-selection benchmark agent.

You are given MCP tool definitions below. Pick exactly ONE tool that best matches the user request.
Do not invent tools. Do not call tools. Do not explain your reasoning.

Reply with ONLY the tool name on a single line (snake_case), nothing else.

## Available tools

{schema_text}
"""


def build_user_prompt(case: PromptCase) -> str:
    return f"User request: {case.prompt}"


def parse_tool_name(text: str, known_tools: set[str]) -> str | None:
    cleaned = text.strip().strip("`\"'")
    if cleaned in known_tools:
        return cleaned

    for line in cleaned.splitlines():
        line = line.strip().strip("`\"'")
        if line in known_tools:
            return line

    for token in re.findall(r"[a-z][a-z0-9_]*", cleaned):
        if token in known_tools:
            return token

    return None


def is_correct(predicted: str | None, case: PromptCase) -> bool:
    if predicted is None:
        return False
    allowed = {case.gold_tool, *case.acceptable_alternatives}
    return predicted in allowed


def pick_tool(
    *,
    model: str,
    strategy: str,
    tools: list[dict[str, Any]],
    case: PromptCase,
    temperature: float = 0.0,
) -> SelectionResult:
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}. Choose from: {', '.join(STRATEGIES)}")

    schema_text = STRATEGIES[strategy](tools)
    known_tools = {t["name"] for t in tools}

    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": build_system_prompt(schema_text)},
            {"role": "user", "content": build_user_prompt(case)},
        ],
        temperature=temperature,
        max_tokens=64,
    )

    raw = (response.choices[0].message.content or "").strip()
    predicted = parse_tool_name(raw, known_tools)
    usage = getattr(response, "usage", None)

    return SelectionResult(
        case_id=case.id,
        strategy=strategy,
        model=model,
        gold_tool=case.gold_tool,
        predicted_tool=predicted,
        correct=is_correct(predicted, case),
        schema_chars=len(schema_text),
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        raw_response=raw,
    )


def run_suite(
    *,
    fixture: str,
    strategy: str,
    model: str,
    temperature: float,
) -> list[SelectionResult]:
    tools = load_fixture(fixture)
    cases = load_prompts(fixture)
    return [
        pick_tool(model=model, strategy=strategy, tools=tools, case=case, temperature=temperature)
        for case in cases
    ]


def summarize(results: list[SelectionResult]) -> dict[str, Any]:
    total = len(results)
    correct = sum(1 for r in results if r.correct)
    return {
        "total": total,
        "correct": correct,
        "pass_at_1": round(correct / total, 4) if total else 0.0,
        "strategy": results[0].strategy if results else None,
        "model": results[0].model if results else None,
        "schema_chars": results[0].schema_chars if results else 0,
    }


def write_results(results: list[SelectionResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summarize(results),
        "results": [r.__dict__ for r in results],
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run filesystem tool-selection eval via LiteLLM")
    parser.add_argument("--fixture", default="filesystem", help="Fixture name under fixtures/")
    parser.add_argument(
        "--strategy",
        choices=sorted(STRATEGIES),
        default="json_minified",
        help="Schema encoding strategy",
    )
    parser.add_argument("--model", default=os.environ.get("CONTEXTBENCH_MODEL", DEFAULT_MODEL))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Results JSON path (default: results/<fixture>-<strategy>.json)",
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required for Anthropic models via LiteLLM")

    results = run_suite(
        fixture=args.fixture,
        strategy=args.strategy,
        model=args.model,
        temperature=args.temperature,
    )

    out_path = args.output or RESULTS_DIR / f"{args.fixture}-{args.strategy}.json"
    write_results(results, out_path)

    summary = summarize(results)
    print(json.dumps(summary, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
