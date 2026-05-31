"""Capture tools/list from an MCP server and save as a fixture."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

SERVER_CONFIGS = {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "requires_allowed_dir": True,
    },
}


async def capture(server: str, allowed_dir: Path, output: Path | None) -> Path:
    config = SERVER_CONFIGS[server]
    command = config["command"]
    args = list(config["args"])
    if config.get("requires_allowed_dir"):
        args.append(str(allowed_dir.resolve()))

    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            tools = [tool.model_dump(mode="json", by_alias=True) for tool in result.tools]

    out_path = output or ROOT / "fixtures" / f"{server}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "server": server,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "command": [command, *args],
                "tool_count": len(tools),
                "tools": tools,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture MCP tools/list as a fixture")
    parser.add_argument("server", choices=sorted(SERVER_CONFIGS))
    parser.add_argument("--allowed-dir", type=Path, default=ROOT / "sandboxes" / "filesystem")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    args.allowed_dir.mkdir(parents=True, exist_ok=True)
    out_path = asyncio.run(capture(args.server, args.allowed_dir, args.output))
    print(f"Captured {args.server} → {out_path}")


if __name__ == "__main__":
    main()
