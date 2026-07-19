"""
MCP Client — Tool Router

Routes tool calls to the appropriate MCP Server.
Servers are registered at startup; Agents call tools through this client.

Architecture rule: MCP is the ONLY execution layer for capabilities.

Namespacing: Tool names are registered as "server_name.tool_name" to prevent
silent overwrites when two servers define tools with the same name.
Callers can use either the short name (if unique) or the fully-qualified
"server.tool" name.
"""

from typing import Any

from app.mcp.base import MCPServerBase, error_response


class MCPClient:
    """MCP client interface — all tool calls go through this class.

    Usage:
        client = MCPClient()
        client.register_server(document_server)
        client.register_server(knowledge_server)

        # Namespaced call
        result = await client.call_tool("ocr.extract_document", {"file_path": "..."})

        # Short name also works if unique across servers
        result = await client.call_tool("extract_document", {"file_path": "..."})
    """

    def __init__(self):
        self._servers: dict[str, MCPServerBase] = {}
        self._tool_to_server: dict[str, str] = {}  # short_name → server_name
        self._namespaced_tools: dict[str, tuple[str, str]] = {}  # server.tool → (server, tool)

    def register_server(self, server: MCPServerBase) -> None:
        """Register an MCP Server and its tools with namespace support.

        Tools are registered as both:
        - "server_name.tool_name" (fully-qualified, guaranteed unique)
        - "tool_name" (short form, logs warning on collision)
        """
        self._servers[server.name] = server
        for tool_info in server.list_tools():
            short_name = tool_info["name"]
            fq_name = f"{server.name}.{short_name}"

            # Always register fully-qualified name
            self._namespaced_tools[fq_name] = (server.name, short_name)

            # Register short name, warn on collision
            if short_name in self._tool_to_server:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Tool name collision: '{short_name}' already registered "
                    f"by '{self._tool_to_server[short_name]}', "
                    f"overwrote by '{server.name}'. "
                    f"Use fully-qualified name '{fq_name}' to avoid ambiguity."
                )
            self._tool_to_server[short_name] = server.name

    def list_tools(self) -> list[dict[str, str]]:
        """List all registered tools with their fully-qualified names."""
        tools = []
        for server in self._servers.values():
            for tool_info in server.list_tools():
                tools.append({
                    "name": f"{server.name}.{tool_info['name']}",
                    "description": tool_info["description"],
                    "server": server.name,
                })
        return tools

    def _resolve_tool_name(self, name: str) -> tuple[str, str] | None:
        """Resolve tool name to (server_name, tool_name).

        Supports both short names and fully-qualified "server.tool" names.
        """
        # Try fully-qualified name first
        if name in self._namespaced_tools:
            return self._namespaced_tools[name]

        # Try short name
        if "." not in name:
            server_name = self._tool_to_server.get(name)
            if server_name:
                return (server_name, name)

        return None

    async def call_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Call a registered MCP tool by name.

        Supports both short names and fully-qualified "server.tool" names.

        Returns the standard MCP response envelope:
        {"success": true, "data": {...}, "error": null}
        or
        {"success": false, "data": null, "error": {"code": "...", "message": "..."}}
        """
        resolved = self._resolve_tool_name(name)
        if resolved is None:
            return error_response(
                "TOOL_NOT_FOUND",
                f"Tool '{name}' is not registered in any MCP Server",
            )

        server_name, tool_name = resolved
        server = self._servers[server_name]
        return await server.execute_tool(tool_name, payload)


# Global MCP client instance
mcp_client = MCPClient()
