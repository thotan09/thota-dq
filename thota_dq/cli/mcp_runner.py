"""MCP server runner — separated to avoid importing mcp at CLI startup."""
from __future__ import annotations


def run_mcp_server(host: str, port: int, transport: str) -> None:
    try:
        from ..integrations.mcp.server import mcp_server
    except ImportError:
        raise SystemExit(
            "MCP support requires 'mcp'. Install with: pip install thota-dq[mcp]"
        )
    if transport == "sse":
        mcp_server.run(transport="sse", host=host, port=port)
    else:
        mcp_server.run(transport="stdio")
