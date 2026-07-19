"""MCP tool registration verification."""
import sys
sys.path.insert(0, ".")
from app.mcp.client import mcp_client

tools = mcp_client.list_tools()
print(f"Total MCP tools registered: {len(tools)}")
print()
by_server = {}
for t in tools:
    by_server.setdefault(t["server"], []).append(t)
for server_name, server_tools in sorted(by_server.items()):
    print(f"  [{server_name}] ({len(server_tools)} tools)")
    for t in server_tools:
        print(f"    {t['name']}: {t['description'][:60]}")
    print()
