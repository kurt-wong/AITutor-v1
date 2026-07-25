"""
Component 3 — VL Verification (Two-Phase) + LaTeX Conversion

Two-phase architecture (C3a + C3b):

  C3a (Qwen 3.6 Plus): OCR correction + role tagging + subject guess — Session #77
  C3b (MIMO V2.5):     LaTeX formula extraction (cloud API)

Session #47: qwythos-9b VL path removed — 100% failure rate on RTX 4060 8GB.
C3b now uses MIMO V2.5 exclusively. No local model swap needed between phases.

Only LOW-confidence blocks (< 0.85) are sent for verification.
HIGH-confidence blocks are passed through directly.

── P2-5: Inherits from VLClient base class (shared MIMO/Ollama/JSON infra).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.document.parallel_extraction._rule_preclassifier import (
    get_rule_confidence,
    preclassify_blocks,
)
from app.domains.document.parallel_extraction._vl_client import VLClient
from app.domains.document.parallel_extraction.latex_fallback import (
    LatexFallbackEngine,
)
from app.domains.document.parallel_extraction.types import (
    ConfidenceTag,
    ContentRole,
    LatexBlock,
    TaggedTextBlock,
    VerifyResult,
)

logger = get_logger("parallel_extraction.c3_verify")


class VLVerifier(VLClient):
    """VL-based OCR verification with two-phase model strategy.

    C3a (OCR verify):  Qwen 3.6 Plus (cloud) — fast, accurate, no local VRAM
    C3b (LaTeX extract): MIMO V2.5 (cloud) — only working backend on RTX 4060 8GB

    Session #47: Ollama C3b path (qwythos-9b) removed — 100% VL failure rate.
    The ``c3b_primary`` parameter is retained for future local VL models but
    defaults to ``"mimo"``. ``safe_model_swap()`` is no longer needed.

    ── P2-5: Inherits shared VL infrastructure from VLClient.
    """

    def __init__(
        self,
        vl_base_url: Optional[str] = None,
        vl_model: Optional[str] = None,
        latex_model: Optional[str] = None,
        timeout: float = 180.0,
        vl_semaphore: Optional[asyncio.Semaphore] = None,
        c3b_primary: Optional[str] = None,
    ):
        # C3a model: Qwen 3.6 Plus for OCR verification (Session #77, same as C4)
        _model = vl_model or getattr(settings, "VL_OCR_MODEL", "qwen3.6-plus")
        super().__init__(
            vl_base_url=vl_base_url or "",
            vl_model=_model,
            vl_primary=getattr(settings, "VL_PRIMARY", "ollama"),
            timeout=timeout,
            vl_semaphore=vl_semaphore,
        )
        # C3b model: MIMO V2.5 (S#128 — VL_C3_MODEL config removed)
        self._latex_model = latex_model or ""
        # C3b primary backend: "mimo" (default) — Ollama path reserved for future
        self._c3b_primary = c3b_primary or getattr(
            settings, "VL_C3B_PRIMARY", "mimo"
        )
        self._ocr_prompt = self._load_prompt()        # C3a: OCR-only
        self._latex_prompt = self._load_latex_prompt()  # C3b: LaTeX-only

    # ── Public API ────────────────────────────────────────────────────

    async def verify_and_convert(
        self,
        blocks_by_page: list[list[TaggedTextBlock]],
        page_images: list[str],
        answer_section=None,
    ) -> VerifyResult:
        """Two-phase VL verification: C3a (Qwen 3.6 Plus) → C3b (LaTeX, MIMO V2.5).

        Phase C3a: OCR correction + role tagging — Qwen 3.6 Plus cloud (Session #77)
        Phase C3b: LaTeX extraction — MIMO V2.5 cloud API

        Only LOW-confidence blocks (< 0.85) are sent for verification.
        HIGH-confidence blocks are passed through directly.

        Args:
            answer_section: Optional Layer 1 boundary. When provided,
                blocks on pages within the boundary default to SOLUTION role
                in the rule preclassifier state machine.
        """
        if not blocks_by_page:
            return VerifyResult()

        # ── Pre-processing (unchanged) ──────────────────────────────
        all_blocks: list[TaggedTextBlock] = [
            b for page_blocks in blocks_by_page for b in page_blocks
        ]
        regex_formulas: list[LatexBlock] = LatexFallbackEngine.extract_from_blocks(
            all_blocks
        )
        logger.info(
            f"C3 regex fallback: {len(regex_formulas)} formula candidates "
            f"from {len(all_blocks)} blocks"
        )

        preclassify_blocks(all_blocks, answer_section=answer_section)
        rule_hits = sum(1 for b in all_blocks if b.role is not None)
        logger.info(
            f"C3 rule preclassifier: {rule_hits}/{len(all_blocks)} blocks "
            f"assigned roles ({rule_hits * 100 // max(len(all_blocks), 1)}%)"
        )

        # Separate LOW and HIGH blocks
        all_high: list[TaggedTextBlock] = []
        low_by_page: dict[int, list[TaggedTextBlock]] = {}

        for page_idx, blocks in enumerate(blocks_by_page):
            for block in blocks:
                if block.tag == ConfidenceTag.LOW:
                    low_by_page.setdefault(page_idx, []).append(block)
                else:
                    all_high.append(block)

        # ── PHASE 1: C3a — OCR Verification (Qwen 3.6 Plus) ──────────
        if low_by_page:
            logger.info(
                f"C3a: Starting OCR verification on "
                f"{sum(len(v) for v in low_by_page.values())} LOW blocks "
                f"across {len(low_by_page)} pages (model={self._vl_model})"
            )
            ocr_tasks = []
            for page_idx, low_blocks in low_by_page.items():
                if page_idx < len(page_images):
                    task = self._verify_page_ocr(low_blocks, page_images[page_idx])
                    ocr_tasks.append(task)

            raw_results: list = await asyncio.gather(
                *ocr_tasks, return_exceptions=True
            )
            page_results: list[dict] = []
            for i, r in enumerate(raw_results):
                if isinstance(r, Exception):
                    logger.warning(f"C3a page verification failed (task {i}): {r}")
                    page_results.append(
                        {"blocks": [], "blocks_corrected": 0, "vl_subjects": []}
                    )
                else:
                    page_results.append(r)
        else:
            page_results = []

        # Merge C3a results
        verified_blocks: list[TaggedTextBlock] = list(all_high)
        vl_subjects_all: list[str] = []
        total_corrected = 0

        for pr in page_results:
            for block in pr.get("blocks", []):
                block.tag = ConfidenceTag.VERIFIED
                verified_blocks.append(block)
            vl_subjects_all.extend(pr.get("vl_subjects", []))
            total_corrected += pr.get("blocks_corrected", 0)

        logger.info(
            f"C3a complete: {total_corrected} blocks corrected, "
            f"{len(verified_blocks)} total blocks"
        )

        # ── PHASE 2: C3b — LaTeX Extraction (MIMO V2.5) ──────────────
        # C3b is OPTIONAL — gracefully degrades to regex fallback when
        # MIMO is unavailable.
        #
        # Session #47: Ollama path (qwythos-9b) removed — 100% VL failure.
        # MIMO V2.5 is the only working C3b backend on RTX 4060 8GB.
        vl_formulas: list[LatexBlock] = []
        c3b_active: bool = False
        _saved_primary: str = self._vl_primary  # restore after C3b

        use_mimo_c3b = (
            self._c3b_primary == "mimo"
            and self._mimo_api_key
            and self._latex_model != self._vl_model
        )

        if use_mimo_c3b:
            # ── MIMO V2.5 Path (cloud, no model swap needed) ─────────
            logger.info(
                f"C3b: Using MIMO V2.5 cloud API (no model swap needed). "
                f"Ollama model {self._vl_model} stays loaded for subsequent calls."
            )
            self._vl_primary = "mimo"
            c3b_active = True

        elif self._latex_model == self._vl_model:
            # Same model for both phases — skip redundant C3b
            logger.info(
                f"C3b: Skipped (same model as C3a: {self._vl_model}). "
                f"Using regex formulas only."
            )
        else:
            # ── Ollama Path (DEPRECATED — Session #47) ───────────────
            # qwythos-9b VL is 100% broken on RTX 4060 8GB.
            # This code path is retained for future local VL models that
            # may become viable. Not reachable with default config
            # (c3b_primary="mimo").
            logger.warning(
                f"C3b: Ollama path is DEPRECATED (Session #47). "
                f"qwythos-9b VL fails 100% on RTX 4060 8GB. "
                f"Skipping C3b — use MIMO V2.5 for LaTeX extraction."
            )
            # c3b_active stays False → skip LaTeX extraction loop below

        if c3b_active:
            # Build per-page verified text for C3b input
            blocks_by_page_corrected: dict[int, list[TaggedTextBlock]] = {}
            for b in verified_blocks:
                blocks_by_page_corrected.setdefault(b.page - 1, []).append(b)

            for page_idx in blocks_by_page_corrected:
                blocks_by_page_corrected[page_idx].sort(
                    key=lambda b: (b.bbox[1] if b.bbox else 0, b.bbox[0] if b.bbox else 0)
                )

            # Run C3b with circuit breaker — if first 2 pages fail, skip remainder
            latex_tasks = []
            for page_idx in range(len(page_images)):
                page_blocks = blocks_by_page_corrected.get(page_idx, [])
                if page_blocks:
                    task = self._extract_page_latex(
                        page_blocks, page_images[page_idx]
                    )
                    latex_tasks.append(task)

            if latex_tasks:
                backend_label = "MIMO V2.5" if use_mimo_c3b else self._latex_model
                logger.info(
                    f"C3b: Extracting LaTeX from {len(latex_tasks)} pages "
                    f"(backend={backend_label})"
                )
                raw_latex: list = await asyncio.gather(
                    *latex_tasks, return_exceptions=True
                )
                consecutive_failures = 0
                for i, r in enumerate(raw_latex):
                    if isinstance(r, Exception):
                        consecutive_failures += 1
                        logger.warning(f"C3b LaTeX extraction failed (task {i}): {r}")
                        # Circuit breaker: after 2 consecutive failures, backend
                        # is likely unavailable — skip remaining.
                        if consecutive_failures >= 2:
                            logger.warning(
                                f"C3b: Circuit breaker tripped after "
                                f"{consecutive_failures} failures — "
                                f"{backend_label} appears unavailable. "
                                f"Skipping remaining {len(raw_latex) - i - 1} pages."
                            )
                            break
                    else:
                        consecutive_failures = 0
                        vl_formulas.extend(r)

            logger.info(f"C3b complete: {len(vl_formulas)} formulas extracted")

            # Restore primary after MIMO path
            if use_mimo_c3b:
                self._vl_primary = _saved_primary
                logger.debug(
                    f"C3b: Restored vl_primary to {self._vl_primary}"
                )

        # ── Merge ───────────────────────────────────────────────────
        subject_guess = VLVerifier._resolve_subject(vl_subjects_all, all_blocks)

        all_formulas = LatexFallbackEngine.merge_formulas(
            vl_formulas, regex_formulas
        )
        logger.info(
            f"C3 formula merge: {len(vl_formulas)} VL + "
            f"{len(regex_formulas)} regex → {len(all_formulas)} unique"
        )

        verified_blocks.sort(key=lambda b: (b.page, b.bbox[1] if b.bbox else 0))

        return VerifyResult(
            blocks=verified_blocks,
            formulas=all_formulas,
            blocks_total=sum(len(b) for b in blocks_by_page),
            blocks_corrected=total_corrected,
            formulas_found=len(all_formulas),
            subject_guess=subject_guess,
        )

    async def verify_single_page(
        self, blocks: list[TaggedTextBlock], page_image_path: str
    ) -> VerifyResult:
        """Verify a single page (useful for testing) — C3a only, no C3b."""
        result = await self._verify_page_ocr(blocks, page_image_path)
        return VerifyResult(
            blocks=result.get("blocks", []),
            formulas=[],  # C3b not run in single-page mode
            blocks_corrected=result.get("blocks_corrected", 0),
            blocks_total=len(blocks),
            formulas_found=0,
        )

    # ── C3a: Per-Page OCR Verification (Qwen 3.6 Plus) ──────────────

    async def _verify_page_ocr(
        self, blocks: list[TaggedTextBlock], page_image_path: str
    ) -> dict:
        """C3a phase: Send one page to VL for OCR correction + role tagging.

        Uses Qwen 3.6 Plus cloud (or VL_OCR_MODEL config). No LaTeX extraction —
        that is deferred to C3b (MIMO V2.5).

        Blocks are batched (max 5 per call) to avoid overwhelming small VL models.
        """
        image_path = Path(page_image_path)
        if not image_path.exists():
            logger.warning(f"Page image not found for OCR verification: {image_path}")
            return {"blocks": blocks, "blocks_corrected": 0, "vl_subjects": []}

        image_b64 = self.encode_image(image_path)

        BATCH_SIZE = 5
        all_verified: list[TaggedTextBlock] = []
        vl_subjects: list[str] = []
        total_corrected = 0
        page_num = blocks[0].page if blocks else 1

        for batch_start in range(0, len(blocks), BATCH_SIZE):
            batch = blocks[batch_start : batch_start + BATCH_SIZE]

            draft_lines: list[str] = []
            for b in batch:
                tag_marker = " [LOW_CONF]" if b.tag == ConfidenceTag.LOW else ""
                draft_lines.append(f"[{b.block_index}]{tag_marker} {b.text}")
            draft_text = "\n".join(draft_lines)

            full_prompt = (
                f"{self._ocr_prompt}\n\n"
                f"=== DRAFT OCR TEXT ===\n{draft_text}\n"
            )

            try:
                raw_response = await self.call_vl(
                    image_b64, full_prompt,
                    mimo_model="mimo-v2.5",
                    mimo_max_tokens=8000,
                    ollama_num_predict=8192,
                    response_validator=self._validate_ocr_response,
                )
                data = self.parse_json(raw_response)

                # Extract VL subject guess
                vl_subject = (
                    data.get("summary", {}).get("subject", "")
                    or data.get("subject", "")
                ).strip().lower()
                if vl_subject:
                    vl_subjects.append(vl_subject)

                if not data.get("blocks"):
                    logger.warning(
                        f"C3a: VL returned no blocks for batch "
                        f"{batch[0].block_index}-{batch[-1].block_index} "
                        f"on page {page_num} — keeping originals"
                    )
                    all_verified.extend(batch)
                    continue

                for vb in data.get("blocks", []):
                    idx = vb.get("index", vb.get("id", 0))
                    corrected = vb.get("corrected_text") or vb.get("text", "")
                    role_str = vb.get("role", "other")
                    conf = vb.get("confidence", 0.9)

                    try:
                        role = ContentRole(role_str)
                    except ValueError:
                        role = ContentRole.OTHER

                    orig = next((b for b in batch if b.block_index == idx), None)

                    if orig is not None:
                        rule_conf = get_rule_confidence(orig)
                        # ── P1-2: Per-role confidence ──
                        # VL now returns role_confidence for role assignment
                        # quality, separate from OCR correction confidence.
                        role_conf = vb.get("role_confidence", conf)
                        if rule_conf >= 0.7 and role == ContentRole.OTHER and orig.role is not None:
                            # VL gave up on role → trust rule-based assignment
                            role = orig.role
                        elif (
                            rule_conf >= 0.7
                            and role_conf < 0.7
                            and orig.role is not None
                            and role != orig.role
                        ):
                            # VL is uncertain about its own role AND
                            # rule is confident → prefer rule-based role
                            role = orig.role

                    all_verified.append(
                        TaggedTextBlock(
                            text=corrected,
                            bbox=orig.bbox if orig else [0, 0, 0, 0],
                            confidence=conf,
                            page=orig.page if orig else page_num,
                            tag=ConfidenceTag.VERIFIED,
                            role=role,
                            block_index=idx,
                        )
                    )

                # Defensive: VL may return blocks_corrected as int, list, or missing
                raw_corrected = data.get("summary", {}).get("blocks_corrected", 0)
                if isinstance(raw_corrected, (int, float)):
                    total_corrected += int(raw_corrected)
                elif isinstance(raw_corrected, list):
                    total_corrected += len(raw_corrected)

            except Exception as e:
                logger.warning(
                    f"C3a batch failed (blocks {batch[0].block_index}-"
                    f"{batch[-1].block_index}): {e}"
                )
                all_verified.extend(batch)
                continue

        return {
            "blocks": all_verified,
            "blocks_corrected": total_corrected,
            "vl_subjects": vl_subjects,
        }

    # ── C3b: Per-Page LaTeX Extraction (MIMO V2.5) ──────────────────

    async def _extract_page_latex(
        self, verified_blocks: list[TaggedTextBlock], page_image_path: str
    ) -> list[LatexBlock]:
        """C3b phase: Extract LaTeX formulas using MIMO V2.5 (or configured backend).

        Sends the full page of verified text with the page image.
        Returns only formula data.
        """
        image_path = Path(page_image_path)
        if not image_path.exists():
            logger.warning(f"Page image not found for LaTeX extraction: {image_path}")
            return []

        page_num = verified_blocks[0].page if verified_blocks else 1

        # Build verified text from all blocks on this page
        verified_lines: list[str] = []
        for b in sorted(verified_blocks, key=lambda x: (
            x.bbox[1] if x.bbox else 0, x.bbox[0] if x.bbox else 0
        )):
            role_str = b.role.value if b.role else "other"
            verified_lines.append(f"[{b.block_index}][{role_str}] {b.text}")
        verified_text = "\n".join(verified_lines)

        full_prompt = (
            f"{self._latex_prompt}\n\n"
            f"=== VERIFIED OCR TEXT ===\n{verified_text}\n"
        )

        raw_response = ""  # bound before try for salvage fallback in except
        try:
            image_b64 = self.encode_image(image_path)
            # C3b timeout: 90s per page
            raw_response = await asyncio.wait_for(
                self.call_vl(
                    image_b64, full_prompt,
                    mimo_model="mimo-v2.5",
                    mimo_max_tokens=4096,
                    ollama_num_predict=12288,
                    ollama_keep_alive=0,
                    max_retries=1,
                    backoff=1.0,
                ),
                timeout=90.0,
            )
            data = self.parse_json(raw_response)

            formulas: list[LatexBlock] = []
            for fb in data.get("formulas", []):
                latex = fb.get("latex", "")
                if not latex or latex.strip() == "":
                    continue
                confidence = fb.get("confidence", 0.9)
                # ── Confidence filter ────────────────────────────
                # MIMO V2.5 occasionally classifies Chinese text (page
                # numbers, headers, mixed text) as display math with
                # low confidence. Drop formulas below 0.75 to reduce
                # noise while preserving genuine low-confidence math.
                if confidence < 0.75:
                    logger.debug(
                        f"C3b page {page_num}: dropped low-confidence "
                        f"formula (conf={confidence:.2f}): {latex[:60]}"
                    )
                    continue
                formulas.append(
                    LatexBlock(
                        latex=latex,
                        display_math=fb.get("display_math", True),
                        confidence=confidence,
                        source_block_index=fb.get("source_block_index"),
                        page=page_num,
                    )
                )

            # ── Fallback: salvage formulas from malformed/mixed JSON ──
            if not formulas and raw_response:
                salvaged = VLClient.salvage_formulas(raw_response)
                if salvaged:
                    logger.info(
                        f"C3b page {page_num}: parse_json returned 0 formulas, "
                        f"salvage extracted {len(salvaged)} via regex"
                    )
                    for fb in salvaged:
                        conf = fb.get("confidence", 0.72)
                        if conf < 0.70:
                            continue
                        formulas.append(
                            LatexBlock(
                                latex=fb["latex"],
                                display_math=fb.get("display_math", True),
                                confidence=conf,
                                source_block_index=fb.get("source_block_index"),
                                page=page_num,
                            )
                        )

            logger.debug(
                f"C3b page {page_num}: {len(formulas)} formulas extracted"
            )
            return formulas

        except Exception as e:
            logger.warning(f"C3b LaTeX extraction failed for page {page_num}: {e}")
            # Last resort: regex salvage from whatever raw text we have
            if raw_response:
                salvaged = VLClient.salvage_formulas(raw_response)
                if salvaged:
                    logger.info(
                        f"C3b page {page_num}: exception recovery — "
                        f"salvage extracted {len(salvaged)} formulas via regex"
                    )
                    formulas: list[LatexBlock] = []
                    for fb in salvaged:
                        if fb.get("confidence", 0.72) >= 0.70:
                            formulas.append(
                                LatexBlock(
                                    latex=fb["latex"],
                                    display_math=fb.get("display_math", True),
                                    confidence=fb.get("confidence", 0.72),
                                    source_block_index=fb.get("source_block_index"),
                                    page=page_num,
                                )
                            )
                    return formulas
            return []

    # ── C3a: OCR response validator (blocks only, no formulas) ─────

    @staticmethod
    def _validate_ocr_response(raw: str) -> bool:
        """Check that VL response contains blocks data (C3a — no formulas needed)."""
        import json as _json

        if not raw or len(raw.strip()) <= 10:
            return False
        try:
            data = _json.loads(raw) if raw.strip().startswith("{") else None
            if not data:
                return False
            return len(data.get("blocks", [])) > 0
        except Exception:
            return False

    # ── Legacy (kept for backward-compat with old callers) ──────────

    @staticmethod
    def _validate_response(raw: str) -> bool:
        """Check that VL response contains blocks data."""
        return VLVerifier._validate_ocr_response(raw)

    # ── P2-1: Subject resolution ────────────────────────────────────

    @staticmethod
    def _resolve_subject(
        vl_subjects: list[str],
        all_blocks: list[TaggedTextBlock],
    ) -> str:
        """Determine the most likely subject from VL votes + text fallback.

        1. Majority vote from VL per-batch subject guesses.
        2. Fallback regex rules when VL provides no guess.
        """
        # Majority vote from VL
        if vl_subjects:
            from collections import Counter
            counter = Counter(vl_subjects)
            top_subject, top_count = counter.most_common(1)[0]
            if top_subject and top_subject != "other":
                logger.info(
                    f"P2-1 subject from VL: {top_subject} "
                    f"({top_count}/{len(vl_subjects)} votes)"
                )
                return top_subject

        # Fallback: regex keyword scan on all blocks
        combined = " ".join(b.text for b in all_blocks if b.text)
        return VLVerifier._guess_subject_from_text(combined)

    @staticmethod
    def _guess_subject_from_text(text: str) -> str:
        """Fallback subject detection via keyword scanning."""
        if not text:
            return ""

        # Physics indicators
        if re.search(
            r"(力|加速度|速度|电场|磁场|电势|电阻|电流|电压"
            r"|牛顿|焦耳|瓦特|欧姆|安培|伏特|库仑|特斯拉"
            r"|动量|动能|势能|波长|频率|折射|干涉|衍射"
            r"|F=ma|v=|a=|E=|B=)",
            text,
        ):
            return "physics"

        # Chemistry indicators
        if re.search(
            r"(反应|溶液|化学|分子|原子|离子|元素|化合价"
            r"|氧化|还原|电解|电离|水解|沉淀|气体"
            r"|mol|pH|H₂|CO₂|NaCl|NaOH|H₂SO₄|Fe|Cu|Al"
            r"|催化剂|加热|点燃|方程式)",
            text,
        ):
            return "chemistry"

        # Biology indicators
        if re.search(
            r"(细胞|基因|DNA|RNA|蛋白质|酶|光合|呼吸"
            r"|遗传|进化|生态|种群|群落|免疫|神经"
            r"|有丝分裂|减数分裂|染色体|ATP|线粒体)",
            text,
        ):
            return "biology"

        # Math indicators (check after physics to avoid force/vector overlap)
        if re.search(
            r"(函数|方程|几何|三角|数列|概率|统计|导数"
            r"|积分|向量|矩阵|集合|log|sin|cos|tan"
            r"|f\(x\)|△|∠|⊥|∥|∞|∑|∏|∫|√)",
            text,
        ):
            return "math"

        # English indicators
        if re.search(r"\b[A-Za-z]{3,}\b", text) and len(re.findall(r"[一-鿿]", text)) < len(text) * 0.1:
            return "english"

        # Chinese indicators (high CJK ratio)
        if len(re.findall(r"[一-鿿]", text)) > len(text) * 0.3:
            return "chinese"

        return ""

    # ── Prompt Loading ────────────────────────────────────────────────

    @staticmethod
    def _load_prompt() -> str:
        """Load the C3a OCR verification prompt (no LaTeX)."""
        import yaml

        prompt_path = (
            Path(__file__).parent / "prompts" / "vl_ocr_verify_latex.yaml"
        )
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("system_prompt", "")

        return (
            "Correct OCR errors in these text blocks using the page image. "
            "Fix misrecognized characters/numbers/punctuation. "
            "Tag each block with a role (stem/option/solution/header/other). "
            "Guess the subject (math/physics/chemistry/biology/chinese/english/other). "
            "Do NOT convert formulas to LaTeX — another model handles that. "
            'Return ONLY valid JSON: {"blocks": [...], "summary": {...}}.'
        )

    @staticmethod
    def _load_latex_prompt() -> str:
        """Load the C3b LaTeX extraction prompt."""
        import yaml

        prompt_path = (
            Path(__file__).parent / "prompts" / "vl_latex_extract.yaml"
        )
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("system_prompt", "")

        return (
            "Scan this page image and the verified OCR text. "
            "Extract ALL mathematical formulas as LaTeX. "
            "Use \\frac, \\sqrt, \\int, \\sum, \\lim, \\sin, \\cos, \\tan, "
            "\\log, \\ln, \\alpha-\\omega, \\leq\\geq\\neq\\approx\\infty, "
            "\\rightarrow\\Rightarrow, \\in\\notin\\subset\\cup\\cap. "
            "Set display_math=true for standalone formulas, false for inline. "
            "Do NOT convert chemical formulas (H₂O, NaCl, CO₂). "
            'Return ONLY valid JSON: {"formulas": [...], "formulas_found": N}.'
        )
