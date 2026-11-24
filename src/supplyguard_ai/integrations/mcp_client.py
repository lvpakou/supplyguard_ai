"""Call a tool on one of our MCP servers (Streamable HTTP). Used by procurement.py and risk.py.

The graph nodes are plain (sync) functions, so call_tool() is sync: it runs the MCP client
in its own event loop, in a worker thread if one is already running (Chainlit).
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def _call(url: str, tool: str, arguments: dict):
    async with streamablehttp_client(url, timeout=10) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
    if result.isError:
        raise RuntimeError(" ".join(getattr(c, "text", "") for c in result.content) or f"{tool} failed")
    if result.structuredContent is not None:            # FastMCP returns typed results here
        data = result.structuredContent
        return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data
    texts = [c.text for c in result.content if getattr(c, "text", None)]
    return json.loads(texts[0]) if len(texts) == 1 else [json.loads(t) for t in texts]


def call_tool(url: str, tool: str, arguments: dict):
    """Run one MCP tool and return its result (a dict or a list)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_call(url, tool, arguments))
    with ThreadPoolExecutor(max_workers=1) as pool:      # we are inside a running loop
        return pool.submit(asyncio.run, _call(url, tool, arguments)).result()
