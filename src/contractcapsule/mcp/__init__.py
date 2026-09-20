"""Narrow, dependency-free MCP transport facade for ContractCapsule."""

from contractcapsule.mcp.server import (
    MCPService,
    handle_json,
    handle_request,
    serve_stdio,
)

__all__ = ["MCPService", "handle_json", "handle_request", "serve_stdio"]
