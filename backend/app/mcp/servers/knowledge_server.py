"""
Knowledge MCP Server (In-Process MCP)

Implements Knowledge MCP tools per MIS §3.2:
- classify_subject: identify subject of a question
- evaluate_difficulty: estimate question difficulty
- map_knowledge: map question to predefined knowledge tree

Architecture: All LLM calls go through LLM Gateway (SAD §16.9).
Prompts loaded from YAML via PromptLoader (prompt.md §2 Rule 4).
"""

import logging
from typing import Any

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.gateway.router import llm_gateway
from app.core.prompt_loader import get_system_prompt, format_prompt
from app.db.session import async_session_factory
from app.domains.knowledge.service import KnowledgeService
from app.domains.knowledge.subject_identifier import SubjectIdentifier

logger = logging.getLogger(__name__)

ALLOWED_SUBJECTS = {"mathematics", "physics", "chemistry", "english", "chinese"}


class KnowledgeMCPServer(MCPServerBase):
    """Knowledge MCP Server for classification and mapping."""

    name = "knowledge"

    def _register_tools(self) -> None:
        # P0 fix: knowledge classification uses fast LLM calls, 45s covers cloud latency
        self.tools = [
            MCPTool(name="classify_subject", description="Identify the subject of a question", handler=self._classify_subject, timeout=45.0),
            MCPTool(name="classify_knowledge_points", description="Classify question into predefined knowledge tree nodes", handler=self._classify_knowledge_points, timeout=45.0),
            MCPTool(name="evaluate_difficulty", description="Estimate question difficulty (1-5)", handler=self._evaluate_difficulty, timeout=45.0),
            MCPTool(name="map_question_to_knowledge", description="Map question to predefined knowledge tree nodes", handler=self._map_knowledge, timeout=45.0),
            MCPTool(name="identify_subject", description="Rule-first subject identification with LLM fallback (Phase 2)", handler=self._identify_subject, timeout=45.0),
        ]

    async def _classify_subject(self, payload: dict[str, Any]) -> dict[str, Any]:
        question_text = payload.get("question_text")
        if not question_text:
            return error_response("VALIDATION_ERROR", "question_text is required")
        try:
            system_prompt = get_system_prompt("subject_classifier")
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}"
            response = await llm_gateway.generate(mode="fast", prompt=full_prompt)

            # Parse LLM response
            parsed = self._parse_json_response(response)
            if parsed and "subject" in parsed:
                subject = parsed["subject"].lower()
                confidence = float(parsed.get("confidence", 0.9))
                if subject in ALLOWED_SUBJECTS:
                    return success_response({"subject": subject, "confidence": confidence})

            # Fallback if parsing fails
            logger.warning("Failed to parse classify_subject response, using fallback")
            return success_response({"subject": "mathematics", "confidence": 0.5})
        except Exception as e:
            return error_response("CLASSIFICATION_FAILED", str(e))

    async def _classify_knowledge_points(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Classify a question into knowledge points from the predefined knowledge tree.

        Uses shared _map_knowledge_impl helper (B8: no tool cross-call).

        Input: {"question_text": str, "subject": Optional[str]}
        Output: {"knowledge_points": [{"name": str, "code": str, "confidence": float}]}
        """
        result = await self._map_knowledge_impl(payload)
        if result["success"] and result["data"]:
            nodes = result["data"].get("knowledge_nodes", [])
            result["data"] = {"knowledge_points": nodes}
        return result

    async def _evaluate_difficulty(self, payload: dict[str, Any]) -> dict[str, Any]:
        question_text = payload.get("question_text")
        if not question_text:
            return error_response("VALIDATION_ERROR", "question_text is required")
        try:
            system_prompt = get_system_prompt("difficulty_classifier")
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}"
            response = await llm_gateway.generate(mode="fast", prompt=full_prompt)

            # Parse LLM response
            parsed = self._parse_json_response(response)
            if parsed and "difficulty" in parsed and parsed["difficulty"] is not None:
                difficulty = int(parsed["difficulty"])
                if 1 <= difficulty <= 5:
                    return success_response({"difficulty": difficulty, "reason": parsed.get("reason", "")})

            # Fallback if parsing fails
            logger.warning("Failed to parse evaluate_difficulty response, using fallback")
            return success_response({"difficulty": 3, "reason": "Unable to determine"})
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, RuntimeError) as e:
            # Graceful fallback when LLM gateway is unavailable
            logger.warning(f"LLM gateway error in evaluate_difficulty: {e}, using fallback")
            return success_response({"difficulty": 3, "reason": "API unavailable"})

    async def _map_knowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        """MCP tool: map question to knowledge tree nodes."""
        return await self._map_knowledge_impl(payload)

    async def _map_knowledge_impl(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Shared implementation for knowledge mapping (B8: avoids tool cross-call)."""
        question_text = payload.get("question_text")
        subject = payload.get("subject", "")
        if not question_text:
            return error_response("VALIDATION_ERROR", "question_text is required")
        try:
            # Load actual knowledge node codes from DB for prompt injection
            async with async_session_factory() as session:
                svc = KnowledgeService(session)
                all_nodes = await svc.list_all_nodes()
                node_codes_block = "\n".join(
                    f"  - id={n.id}, code={n.code}, name={n.name}" for n in all_nodes
                )

            # Use format_prompt to inject both subject and knowledge_nodes into template
            system_prompt = format_prompt(
                "knowledge_mapper",
                subject=subject,
                knowledge_nodes=node_codes_block,
            )
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}"
            response = await llm_gateway.generate(mode="fast", prompt=full_prompt)

            # Parse LLM response
            parsed = self._parse_json_response(response)
            if parsed and "knowledge_nodes" in parsed:
                # Validate nodes against database (reuse already-fetched all_nodes)
                valid_ids = {str(n.id) for n in all_nodes}

                validated_nodes = []
                for node in parsed["knowledge_nodes"]:
                    node_id = str(node.get("id", ""))
                    if node_id in valid_ids:
                        validated_nodes.append({
                            "id": node_id,
                            "code": node.get("code", ""),
                            "confidence": float(node.get("confidence", 0.8))
                        })

                if validated_nodes:
                    return success_response({"knowledge_nodes": validated_nodes})

            # Fallback: use database nodes (reuse already-fetched all_nodes)
            logger.warning("Failed to parse map_knowledge response, using database fallback")
            subject_nodes = [n for n in all_nodes if n.name != "UNKNOWN"]
            unknown_node = next((n for n in all_nodes if n.name == "UNKNOWN"), None)
            if subject_nodes:
                return success_response({"knowledge_nodes": [{"id": str(n.id), "code": n.code, "confidence": 0.5} for n in subject_nodes[:2]]})
            elif unknown_node:
                return success_response({"knowledge_nodes": [{"id": str(unknown_node.id), "code": unknown_node.code, "confidence": 0.3}]})
            else:
                return success_response({"knowledge_nodes": []})
        except Exception as e:
            return error_response("MAPPING_FAILED", str(e))

    async def _identify_subject(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Rule-first subject identification (Phase 2).

        Priority chain:
        1. Keyword rule matching (fast, deterministic)
        2. Knowledge tree node matching
        3. LLM-based fallback

        Input: {"question_text": str, "knowledge_node_id": Optional[int], "images": Optional[List[str]]}
        Output: {"subject": str, "method": str, "confidence": float}
        """
        question_text = payload.get("question_text", "")
        knowledge_node_id = payload.get("knowledge_node_id")
        images = payload.get("images")

        if not question_text and not images:
            return error_response("VALIDATION_ERROR", "question_text or images is required")

        try:
            # Step 1-2: Rule-based identification (keyword + knowledge tree)
            async with async_session_factory() as session:
                identifier = SubjectIdentifier(session)
                result = await identifier.identify(question_text, knowledge_node_id)

            # If rules found a match with high confidence, return immediately
            if result["method"] != "unknown":
                return success_response({
                    "subject": result["subject"],
                    "method": result["method"],
                    "confidence": result["confidence"],
                    "matched_keyword": result.get("matched_keyword"),
                    "matched_node": result.get("matched_node"),
                    "matched_code": result.get("matched_code"),
                })

            # Step 3: LLM-based fallback
            system_prompt = get_system_prompt("subject_identifier")
            prompt_text = question_text or "[Image-based question — identify subject from visual content]"
            full_prompt = f"{system_prompt}\n\nQuestion: {prompt_text}"

            response = await llm_gateway.generate(
                mode="fast",
                prompt=full_prompt,
                images=images,
            )

            parsed = self._parse_json_response(response)
            if parsed and "subject" in parsed:
                subject = parsed["subject"].lower()
                confidence = float(parsed.get("confidence", 0.8))
                if subject in ALLOWED_SUBJECTS:
                    return success_response({
                        "subject": subject,
                        "method": "llm",
                        "confidence": confidence,
                        "keywords_found": parsed.get("keywords_found", []),
                        "reasoning": parsed.get("reasoning", ""),
                    })

            # Ultimate fallback
            logger.warning("Failed to identify subject, using default")
            return success_response({
                "subject": "mathematics",
                "method": "default",
                "confidence": 0.3,
            })

        except Exception as e:
            return error_response("CLASSIFICATION_FAILED", str(e))
