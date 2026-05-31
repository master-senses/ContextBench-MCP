"""Capture tools/list from an MCP server and save as a fixture."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "fixtures"

# Official MCP servers we support for fixture capture.
SERVER_CONFIGS: dict[str, dict[str, Any]] = {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        # Allowed directory passed as final arg at runtime.
        "requires_allowed_dir": True,
    },
}


async def list_tools(command: str, args: list[str]) -> list[dict[str, Any]]:
    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [tool.model_dump(mode="json", by_alias=True) for tool in result.tools]


def build_server_args(server: str, allowed_dir: Path) -> tuple[str, list[str]]:
    config = SERVER_CONFIGS[server]
    command = config["command"]
    args = list(config["args"])
    if config.get("requires_allowed_dir"):
        args.append(str(allowed_dir.resolve()))
    return command, args


async def capture(server: str, allowed_dir: Path, output: Path | None) -> Path:
    if server not in SERVER_CONFIGS:
        raise SystemExit(f"Unknown server {server!r}. Supported: {', '.join(SERVER_CONFIGS)}")

    command, args = build_server_args(server, allowed_dir)
    tools = await list_tools(command, args)

    fixture = {
        "server": server,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "command": [command, *args],
        "tool_count": len(tools),
        "tools": tools,
    }

    out_path = output or FIXTURES_DIR / f"{server}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture MCP tools/list as a fixture")
    parser.add_argument("server", choices=sorted(SERVER_CONFIGS), help="MCP server to capture")
    parser.add_argument(
        "--allowed-dir",
        type=Path,
        default=ROOT / "sandboxes" / "filesystem",
        help="Allowed directory for servers that require one (default: sandboxes/filesystem)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: fixtures/<server>.json)",
    )
    args = parser.parse_args()

    args.allowed_dir.mkdir(parents=True, exist_ok=True)
    out_path = asyncio.run(capture(args.server, args.allowed_dir, args.output))
    print(f"Captured {args.server} → {out_path}")


if __name__ == "__main__":
    main()
