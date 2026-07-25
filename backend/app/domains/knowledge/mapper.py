"""
Knowledge Mapper — StructuredQuestion → KnowledgeNode[]

Rule-first knowledge point mapping against 9-subject knowledge tree:
  1. Keyword matching (fast, deterministic, covers ~60%)
  2. Question-type heuristics (choice→concept, fill→computation, proof→synthesis)
  3. Cross-disciplinary expansion via DAG edges
  4. LLM fallback via llm_gateway

Supports 9 subjects: MATH/PHYS/CHEM/BIO/CHN/ENG/POLI/HIST/GEOG
"""

from __future__ import annotations

import json
import re

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.domains.question.structurer import StructuredQuestion

logger = get_logger("knowledge.mapper")


# ═══ Output Types ════════════════════════════════════════════════════════════

@dataclass
class KnowledgeMapping:
    """Result of mapping a question to a knowledge node."""

    node_code: str
    node_name: str = ""
    confidence: float = 1.0
    method: str = "keyword"  # "keyword" | "type_heuristic" | "llm" | "default"
    matched_keyword: str = ""


# ═══ Mapper ══════════════════════════════════════════════════════════════════

class KnowledgeMapper:
    """Rule-first knowledge point mapper.

    Maps StructuredQuestion → list[KnowledgeMapping] using:
    1. Keyword matching against 人教版高中数学 knowledge tree (~150 nodes)
    2. Question-type heuristics (choice/fill/proof)
    3. LLM fallback (optional async path)

    Pure logic for steps 1-2 — no I/O, easy to unit-test.
    """

    def __init__(self):
        self._keyword_index: dict[str, list[str]] | None = None

    @property
    def keyword_index(self) -> dict[str, list[str]]:
        """Lazy-load the keyword→node_code index."""
        if self._keyword_index is None:
            from app.domains.knowledge.tree_seed import get_keyword_index

            self._keyword_index = get_keyword_index()
        return self._keyword_index

    # ── Public API ──────────────────────────────────────────────────────

    async def map_question(
        self,
        question: "StructuredQuestion",
        top_k: int = 3,
        subject: str | None = None,
        enable_cross_refs: bool = True,
    ) -> list[KnowledgeMapping]:
        """Map a structured question to knowledge points (with LLM fallback).

        Args:
            question: StructuredQuestion from the structurer pipeline.
            top_k: Maximum number of knowledge points to return.
            subject: Subject code. Auto-detected from keyword match if None.
            enable_cross_refs: Expand results with cross-disciplinary links.

        Returns:
            list of KnowledgeMapping, sorted by confidence descending.
        """
        text = self._question_text(question)

        # Step 1: Keyword matching
        keyword_results = self._match_keywords(text, subject=subject)
        detected_subject = self._detect_subject(keyword_results) if not subject else subject

        if keyword_results:
            results = keyword_results[:top_k]
            # Step 1.5: Expand cross-references
            if enable_cross_refs and detected_subject:
                expanded = self._expand_cross_refs(results, detected_subject)
                results = (results + expanded)[:top_k]
            logger.debug(
                f"Q{question.question_number}: keyword match → "
                f"{[m.node_code for m in results]}"
            )
            return results

        # Step 2: Type heuristic
        type_result = self._match_by_type(question.question_type, subject=detected_subject)
        if type_result:
            logger.debug(
                f"Q{question.question_number}: type heuristic → "
                f"{type_result.node_code}"
            )
            return [type_result]

        # Step 3: LLM fallback
        logger.info(
            f"Q{question.question_number}: no rule match, invoking LLM fallback"
        )
        llm_results = await self._llm_fallback(text, subject=detected_subject or "mathematics")
        return llm_results[:top_k]

    def map_sync(
        self,
        question: "StructuredQuestion",
        top_k: int = 3,
        subject: str | None = None,
    ) -> list[KnowledgeMapping]:
        """Synchronous version — keyword + type only, no LLM.

        Args:
            question: StructuredQuestion from structurer pipeline.
            top_k: Max knowledge points to return.
            subject: Subject code (e.g. "MATH"). Auto-detected if None.
        """
        text = self._question_text(question)

        # Step 1: Keyword matching
        keyword_results = self._match_keywords(text, subject=subject)
        if keyword_results:
            return keyword_results[:top_k]

        # Step 2: Type heuristic
        type_result = self._match_by_type(question.question_type, subject=subject)
        if type_result:
            return [type_result]

        # Step 3: Cross-disciplinary expansion
        if subject:
            cross_results = self._expand_cross_refs(keyword_results, subject)
            if cross_results:
                return cross_results[:top_k]

        fallback_code = f"{subject}-UNKNOWN" if subject else "UNKNOWN"
        return [
            KnowledgeMapping(
                node_code=fallback_code,
                node_name="UNKNOWN",
                confidence=0.0,
                method="default",
            )
        ]

    # ── Step 1: Keyword Matching ────────────────────────────────────────

    def _match_keywords(self, text: str, subject: str | None = None) -> list[KnowledgeMapping]:
        """Match question text against keyword index.

        Returns deduplicated list sorted by specificity (deeper level first)
        then by match frequency. Optionally filtered by subject.
        """
        code_counter: Counter = Counter()
        code_keyword: dict[str, str] = {}

        text_lower = text.lower()

        for keyword, codes in self.keyword_index.items():
            if keyword in text_lower:
                for code in codes:
                    # Filter by subject if specified
                    if subject and not code.startswith(subject + "-"):
                        continue
                    code_counter[code] += 1
                    if code not in code_keyword:
                        code_keyword[code] = keyword

        if not code_counter:
            return []

        # Sort: prefer deeper codes (more specific), then by frequency
        def _sort_key(code: str) -> tuple[int, int]:
            depth = code.count("-")  # MATH = 0, MATH-FUNC = 1, MATH-FUNC-01 = 2, MATH-FUNC-01-03 = 3
            return (-depth, -code_counter[code])

        sorted_codes = sorted(code_counter.keys(), key=_sort_key)

        results: list[KnowledgeMapping] = []
        for code in sorted_codes:
            results.append(
                KnowledgeMapping(
                    node_code=code,
                    confidence=min(0.95, 0.5 + 0.15 * code_counter[code]),
                    method="keyword",
                    matched_keyword=code_keyword[code],
                )
            )

        return results

    # ── Step 2: Type Heuristics ─────────────────────────────────────────

    @staticmethod
    def _match_by_type(question_type: str, subject: str | None = None) -> KnowledgeMapping | None:
        """Fallback mapping based on question type when keywords miss.

        Subject-aware fallbacks — uses subject prefix when available.
        Session #111: English choice/fill questions default to ENG-VOCAB
        instead of ENG-UNKNOWN since standalone word/phrase options are
        characteristic of vocabulary/cloze exercises.
        """
        subj = subject + "-" if subject else "MATH-"

        # Subject-specific overrides for better fallback granularity
        _SUBJ_OVERRIDES: dict[str, dict[str, tuple[str, str]]] = {
            "ENG": {
                "choice": ("ENG-VOCAB", "词汇选择题"),
                "fill": ("ENG-VOCAB", "词汇填空题"),
                "essay": ("ENG-WRITE", "写作题"),
            },
        }
        if subject and subject in _SUBJ_OVERRIDES:
            override = _SUBJ_OVERRIDES[subject].get(question_type)
            if override:
                return KnowledgeMapping(
                    node_code=override[0],
                    node_name=override[1],
                    confidence=0.35,
                    method="type_heuristic",
                )

        _TYPE_FALLBACK: dict[str, tuple[str, str]] = {
            "choice": (f"{subj}UNKNOWN", "选择题通用"),
            "multi_choice": (f"{subj}UNKNOWN", "多选题通用"),
            "fill": (f"{subj}UNKNOWN", "填空题通用"),
            "proof": (f"{subj}UNKNOWN", "证明题通用"),
            "calculation": (f"{subj}UNKNOWN", "计算题通用"),
            "essay": (f"{subj}UNKNOWN", "问答题通用"),
        }
        fb = _TYPE_FALLBACK.get(question_type)
        if fb:
            return KnowledgeMapping(
                node_code=fb[0],
                node_name=fb[1],
                confidence=0.3,
                method="type_heuristic",
            )
        return None

    # ── Cross-Referencing Support ──────────────────────────────────────

    @staticmethod
    def _detect_subject(results: list[KnowledgeMapping]) -> str | None:
        """Detect dominant subject from keyword match results."""
        if not results:
            return None
        subject_counter: Counter = Counter()
        for r in results:
            prefix = r.node_code.split("-")[0] if "-" in r.node_code else r.node_code
            if len(prefix) <= 4:
                subject_counter[prefix] += 1
        return subject_counter.most_common(1)[0][0] if subject_counter else None

    @staticmethod
    def _expand_cross_refs(
        results: list[KnowledgeMapping], subject: str
    ) -> list[KnowledgeMapping]:
        """Expand results with cross-disciplinary DAG references."""
        from app.domains.knowledge.tree_seed.index_builder import (
            get_cross_refs_for_node,
            get_node_by_code,
        )

        expanded: list[KnowledgeMapping] = []
        seen_codes = {r.node_code for r in results}

        for r in results:
            cross_codes = get_cross_refs_for_node(r.node_code)
            for cc in cross_codes:
                if cc in seen_codes:
                    continue
                seen_codes.add(cc)
                node = get_node_by_code(cc)
                expanded.append(KnowledgeMapping(
                    node_code=cc,
                    node_name=node.name if node else cc,
                    confidence=round(r.confidence * 0.7, 2),
                    method="cross_ref",
                    matched_keyword=r.matched_keyword,
                ))

        return expanded

    # ── Step 3: LLM Fallback (P4c) ──────────────────────────────────────

    async def _llm_fallback(
        self,
        question_text: str,
        subject: str = "mathematics",
    ) -> list[KnowledgeMapping]:
        """LLM-based knowledge mapping fallback for uncovered cases.

        Calls llm_gateway with the knowledge_mapper prompt template,
        injecting available knowledge nodes from DB for validation.

        On any failure (network, parse error, no nodes), returns
        MATH-UNKNOWN with confidence 0.0 so the caller can degrade.
        """
        try:
            from app.db.session import async_session_factory
            from app.domains.knowledge.repository import KnowledgeRepository
            from app.gateway.router import llm_gateway
            from app.core.prompt_loader import format_prompt

            # Fetch knowledge nodes for prompt injection
            async with async_session_factory() as session:
                repo = KnowledgeRepository(session)
                all_nodes = await repo.list_all()
                if not all_nodes:
                    logger.warning("LLM fallback: no knowledge nodes in DB")
                    return self._unknown_result()

                node_codes_block = "\n".join(
                    f"  - id={n.id}, code={n.code}, name={n.name}"
                    for n in all_nodes
                )

            system_prompt = format_prompt(
                "knowledge_mapper",
                subject=subject,
                knowledge_nodes=node_codes_block,
            )
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}"
            # MCP 豁免: KnowledgeMapper 是 KnowledgeServer 的内部实现依赖，
            # 直接调用 LLM Gateway。对外 MCP tool map_question_to_knowledge
            # 已由 knowledge_server.py 提供。
            response = await llm_gateway.generate(mode="fast", prompt=full_prompt)

            raw_text = response.get("response", "")
            if not raw_text or not raw_text.strip():
                logger.warning("LLM fallback: empty response")
                return self._unknown_result()

            # Parse JSON from LLM response (may contain markdown fences)
            data = self._parse_llm_json(raw_text)
            if not data or "knowledge_nodes" not in data:
                logger.warning(
                    f"LLM fallback: unparseable response: {raw_text[:200]}"
                )
                return self._unknown_result()

            # Build results from LLM output
            valid_codes = {n.code for n in all_nodes}
            results: list[KnowledgeMapping] = []
            for node in data["knowledge_nodes"]:
                code = node.get("code", "MATH-UNKNOWN")
                # Validate code exists in DB
                if code not in valid_codes:
                    logger.debug(f"LLM fallback: unknown code '{code}', skipping")
                    continue
                results.append(KnowledgeMapping(
                    node_code=code,
                    node_name=node.get("name", ""),
                    confidence=float(node.get("confidence", 0.7)),
                    method="llm",
                ))

            if results:
                logger.info(f"LLM fallback: mapped to {[r.node_code for r in results]}")
                return results

            return self._unknown_result()

        except Exception as e:
            logger.warning(f"LLM fallback failed: {e}")
            return self._unknown_result()

    @staticmethod
    def _parse_llm_json(raw_text: str) -> dict | None:
        """Extract JSON object from LLM response text.

        Handles markdown fences (```json ... ```) and bare JSON.
        """
        # Strip markdown code fences
        fence_match = re.search(
            r"```(?:json)?\s*([\s\S]*?)```", raw_text
        )
        text = fence_match.group(1).strip() if fence_match else raw_text.strip()

        # Find the outermost JSON object
        brace_start = text.find("{")
        if brace_start == -1:
            return None

        # Try parsing from brace_start
        try:
            return json.loads(text[brace_start:])
        except json.JSONDecodeError:
            pass

        # Fallback: find balanced braces
        depth = 0
        for i, ch in enumerate(text[brace_start:], brace_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    @staticmethod
    def _unknown_result() -> list[KnowledgeMapping]:
        """Return the terminal fallback when all methods fail."""
        return [
            KnowledgeMapping(
                node_code="MATH-UNKNOWN",
                node_name="UNKNOWN",
                confidence=0.0,
                method="default",
            )
        ]

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _question_text(q: "StructuredQuestion") -> str:
        """Combine all question text fields for keyword matching."""
        parts: list[str] = [q.stem]
        parts.extend(q.options)
        if q.answer:
            parts.append(q.answer)
        parts.extend(q.explanation_steps)
        return "\n".join(parts)
