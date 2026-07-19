"""
MCP Package — Model Context Protocol tool layer.

Exports:
- mcp_client: global MCPClient instance (pre-registered)
- MCPClient: routes tool calls to registered MCP Servers
- MCPServerBase: base class for MCP Server implementations
- MCPTool: individual tool definition
- success_response / error_response: standard response envelope
"""

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.mcp.client import MCPClient, mcp_client

__all__ = [
    "MCPClient",
    "mcp_client",
    "MCPServerBase",
    "MCPTool",
    "success_response",
    "error_response",
]
