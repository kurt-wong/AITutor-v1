"""
MCP Server Base Interface (In-Process MCP)

Defines the base class for all MCP Servers and the tool registration pattern.
Each MCP Server exposes a set of tools that Agents can call.

NOTE: This is an In-Process MCP implementation (function call routing),
NOT Anthropic MCP protocol (STDIO/JSON-RPC). This is the correct choice
for a single-user, single-server Docker Compose deployment.

Architecture rules (MIS v1.5):
- Tools are stateless, single-responsibility
- Tools MUST NOT call other tools within the same Server
- Cross-Server tool calls go through Service layer
- All tool outputs comply with standard response envelope

Observability (Project Rules Section 9):
- Every request includes request_id, trace_id, latency, MCP tools used
"""

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


def success_response(data: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a standard success response."""
    response = {"success": True, "data": data, "error": None}
    if metadata:
        response["metadata"] = metadata
    return response


def error_response(code: str, message: str) -> dict[str, Any]:
    """Create a standard error response.

    Defined error codes (per ACS §4):
    - VALIDATION_ERROR: input validation failed
    - TOOL_NOT_FOUND: requested MCP tool not registered
    - TOOL_EXECUTION_ERROR: tool handler raised an exception
    - MCP_TIMEOUT: tool execution exceeded time limit
    - EMPTY_RESULT: tool completed but returned no data
    - LLM_FAILURE / CLASSIFICATION_FAILED / MAPPING_FAILED: domain-specific errors
    """
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message},
    }


ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class MCPTool:
    """Represents a single MCP tool with its metadata.

    input_schema: Optional dict defining required fields and their types.
        Format: {"field_name": {"type": "str|int|float|bool|list|dict", "required": bool}}

    Example:
        MCPTool(
            name="extract_document",
            description="Extract text from a document",
            handler=self._extract_document,
            input_schema={
                "file_path": {"type": "str", "required": True},
                "file_type": {"type": "str", "required": False},
            },
        )
    """

    def __init__(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
        input_schema: dict[str, dict[str, Any]] | None = None,
        timeout: float = 30.0,
    ):
        self.name = name
        self.description = description
        self.handler = handler
        self.input_schema = input_schema
        self.timeout = timeout

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool with input validation and timeout protection.

        Timeout: configurable per-tool (default 30s). LLM-calling tools use
        longer timeouts (120s) to accommodate cloud API latency.
        """
        if self.input_schema:
            error = self._validate_payload(payload)
            if error:
                return error_response("VALIDATION_ERROR", error)
        try:
            return await asyncio.wait_for(self.handler(payload), timeout=self.timeout)
        except asyncio.TimeoutError:
            return error_response(
                "MCP_TIMEOUT",
                f"Tool '{self.name}' execution timed out after {self.timeout:.0f}s",
            )
        except Exception as e:
            return error_response("TOOL_EXECUTION_ERROR", str(e))

    def _validate_payload(self, payload: dict[str, Any]) -> str | None:
        """Validate payload against input_schema. Returns error message or None."""
        for field_name, schema in self.input_schema.items():
            is_required = schema.get("required", False)
            expected_type = schema.get("type")

            value = payload.get(field_name)

            # Check required
            if is_required and (value is None or value == ""):
                return f"'{field_name}' is required"

            # Check type if present and non-None
            if value is not None and expected_type:
                type_map = {
                    "str": str, "int": int, "float": float,
                    "bool": bool, "list": list, "dict": dict,
                }
                py_type = type_map.get(expected_type)
                if py_type and not isinstance(value, py_type):
                    return (
                        f"'{field_name}' expected type '{expected_type}', "
                        f"got '{type(value).__name__}'"
                    )

        return None


class MCPServerBase(ABC):
    """Base class for all MCP Servers (In-Process implementation).

    Subclasses must implement _register_tools() to populate self.tools.

    Observability features (Project Rules Section 9):
    - Generates request_id and trace_id for each tool execution
    - Tracks latency for each tool execution
    - Logs MCP tools used
    """

    name: str = ""

    def __init__(self):
        self.tools: list[MCPTool] = []
        self._tool_map: dict[str, MCPTool] = {}
        self._register_tools()
        for tool in self.tools:
            self._tool_map[tool.name] = tool

    @abstractmethod
    def _register_tools(self) -> None:
        """Register all tools for this server."""
        ...

    @staticmethod
    def _parse_json_response(response: dict) -> dict | None:
        """Parse JSON from LLM response text.

        Handles both ```json code blocks and raw JSON objects.
        Returns None if no valid JSON found.

        P2 fix (2026-07-13): Added robust JSON repair for common LLM
        output issues — trailing commas, NaN/Infinity, LaTeX backslash
        escapes that would otherwise cause parse failures and leak raw
        JSON into final_answer.
        """
        import json as _json
        import re as _re
        try:
            text = response.get("response", "")

            # ── Step 0: Strip <think> tags (some models leak these) ──
            text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()

            # ── Step 1: Try ```json code blocks ──
            if "```json" in text:
                start = text.find("```json") + 7
                end = text.find("```", start)
                if end != -1:
                    candidate = text[start:end].strip()
                    return MCPServerBase._robust_json_loads(candidate)
            # Also try ``` without language specifier
            if "```" in text:
                start = text.find("```") + 3
                end = text.find("```", start)
                if end != -1 and start < end:
                    candidate = text[start:end].strip()
                    if candidate and candidate[0] in ("{", "["):
                        result = MCPServerBase._robust_json_loads(candidate)
                        if result is not None:
                            return result

            # ── Step 2: Find raw JSON object ──
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                candidate = text[start:end]
                return MCPServerBase._robust_json_loads(candidate)

            return None
        except (_json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _robust_json_loads(text: str) -> dict | None:
        """Attempt json.loads with progressive repair for common LLM issues.

        P2 fix: Repairs trailing commas, NaN/Infinity, and LaTeX
        backslash escapes before giving up.  Returns None only if all
        repair strategies fail.

        P3 fix (2026-07-14): Added Python-literal repair (None→null,
        True→true, False→false), unescaped-newline repair, and
        ast.literal_eval fallback for Python dict-style output.
        """
        import json as _json
        import re as _re

        # ── Attempt 1: direct parse ──
        try:
            result = _json.loads(text)
            if isinstance(result, dict):
                return result
            # If it's a list, wrap it — some models return top-level arrays
            if isinstance(result, list):
                return {"items": result}
            return None
        except _json.JSONDecodeError:
            pass

        # ── Attempt 2: repair NaN/Infinity → null ──
        repaired = text
        repaired = _re.sub(r':\s*NaN\b', ': null', repaired)
        repaired = _re.sub(r':\s*Infinity\b', ': null', repaired)
        repaired = _re.sub(r':\s*-Infinity\b', ': null', repaired)
        try:
            result = _json.loads(repaired)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"items": result}
        except _json.JSONDecodeError:
            pass

        # ── Attempt 3: remove trailing commas before ] or } ──
        repaired2 = _re.sub(r",\s*([}\]])", r"\1", repaired)
        try:
            result = _json.loads(repaired2)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"items": result}
        except _json.JSONDecodeError:
            pass

        # ── Attempt 4: fix LaTeX backslash escapes ──
        # LLMs emit \\frac, \\sqrt, etc. inside JSON strings.
        # json.loads treats \\b, \\f, \\n, \\r, \\t as escapes,
        # corrupting LaTeX commands or raising JSONDecodeError.
        repaired3 = _re.sub(
            r'(?<!\\)\\([a-z]{2,}|[A-Z][a-z]*)',
            r'\\\\\1',
            repaired2,
        )
        repaired3 = _re.sub(
            r'(?<!\\)\\([^a-zA-Z"\\/bfnrtu])',
            r'\\\\\1',
            repaired3,
        )
        try:
            result = _json.loads(repaired3)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"items": result}
        except _json.JSONDecodeError:
            pass

        # ── Attempt 5: P3 — Python literal repair ──
        # Some models output Python dicts with None/True/False and
        # single-quoted keys/values instead of proper JSON.
        repaired4 = repaired3
        repaired4 = _re.sub(r'\bNone\b', 'null', repaired4)
        repaired4 = _re.sub(r'\bTrue\b', 'true', repaired4)
        repaired4 = _re.sub(r'\bFalse\b', 'false', repaired4)
        try:
            result = _json.loads(repaired4)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"items": result}
        except _json.JSONDecodeError:
            pass

        # ── Attempt 6: P3 — unescaped newlines in JSON strings ──
        # LLMs sometimes emit real newlines inside string values,
        # which are invalid in JSON.  Replace them with \\n.
        # Only target newlines inside quoted strings (between " pairs
        # on the same logical line).
        def _escape_string_newlines(s: str) -> str:
            """Replace raw newlines inside JSON strings with \\n."""
            result_parts = []
            in_string = False
            escape = False
            for ch in s:
                if escape:
                    result_parts.append(ch)
                    escape = False
                    continue
                if ch == '\\':
                    result_parts.append(ch)
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    result_parts.append(ch)
                    continue
                if in_string and ch == '\n':
                    result_parts.append('\\n')
                    continue
                if in_string and ch == '\r':
                    result_parts.append('\\r')
                    continue
                if in_string and ch == '\t':
                    result_parts.append('\\t')
                    continue
                result_parts.append(ch)
            return ''.join(result_parts)

        repaired5 = _escape_string_newlines(repaired4)
        if repaired5 != repaired4:
            try:
                result = _json.loads(repaired5)
                if isinstance(result, dict):
                    return result
                if isinstance(result, list):
                    return {"items": result}
            except _json.JSONDecodeError:
                pass

        # ── Attempt 7: P3 — ast.literal_eval fallback ──
        # Last resort: try Python literal parsing for dict output.
        # Only attempt if the text looks like a Python dict.
        stripped = text.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                import ast as _ast
                py_obj = _ast.literal_eval(stripped)
                if isinstance(py_obj, dict):
                    # Convert Python values to JSON-compatible ones
                    return py_obj
            except (ValueError, SyntaxError, MemoryError):
                pass

        return None

    def get_tool(self, name: str) -> MCPTool | None:
        """Get a tool by name."""
        return self._tool_map.get(name)

    def list_tools(self) -> list[dict[str, str]]:
        """List all tools with their names and descriptions."""
        return [{"name": t.name, "description": t.description} for t in self.tools]

    async def execute_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by name with observability tracking.

        Per Project Rules Section 9, every request includes:
        - request_id: Unique identifier for this request
        - trace_id: Unique identifier for tracing (propagated from caller if present)
        - latency: Execution time in milliseconds
        - MCP tools used: Logged for observability

        Args:
            tool_name: Name of the tool to execute
            payload: Tool input payload

        Returns:
            Standard response envelope with metadata
        """
        # Generate observability IDs (use .get() to avoid mutating caller's dict)
        request_id = str(uuid.uuid4())
        trace_id = payload.get("_trace_id", str(uuid.uuid4()))

        # Extract caller-provided metadata if present
        caller_request_id = payload.get("_request_id", None)

        # Strip internal metadata before passing to tool handler
        tool_payload = {k: v for k, v in payload.items() if not k.startswith("_")}

        # Start timing
        start_time = time.time()

        # Get tool
        tool = self.get_tool(tool_name)
        if tool is None:
            latency_ms = (time.time() - start_time) * 1000
            logger.warning(
                f"MCP tool not found: {tool_name}",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "server": self.name,
                    "tool": tool_name,
                    "latency_ms": round(latency_ms, 2),
                }
            )
            return error_response("TOOL_NOT_FOUND", f"Tool '{tool_name}' not found in server '{self.name}'")

        # Execute tool
        try:
            result = await tool.execute(tool_payload)
            latency_ms = (time.time() - start_time) * 1000

            # Log successful execution
            logger.info(
                f"MCP tool executed: {self.name}.{tool_name}",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "server": self.name,
                    "tool": tool_name,
                    "latency_ms": round(latency_ms, 2),
                    "success": result.get("success", False),
                }
            )

            # Add metadata to response
            if isinstance(result, dict):
                result["metadata"] = {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "latency_ms": round(latency_ms, 2),
                    "server": self.name,
                    "tool": tool_name,
                }

            return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000

            # Log failed execution
            logger.error(
                f"MCP tool failed: {self.name}.{tool_name}",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "server": self.name,
                    "tool": tool_name,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e),
                },
                exc_info=True
            )

            return error_response("TOOL_EXECUTION_ERROR", str(e))
