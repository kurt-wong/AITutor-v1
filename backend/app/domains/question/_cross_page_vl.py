"""
Cross-Page VL Verifier — Session #25
=====================================
Lightweight, synchronous VL-based second opinion for cross-page merge decisions.

Acts as a **false-positive filter** on ``_should_merge`` decisions:
only called when text rules say "merge".  Can veto merges but cannot
rescue false negatives (recall preserved, precision improved).

Architecture (strategy pattern)::

    CrossPageVLVerifier
      ├── MIMOChatBackend   → POST {MIMO_BASE_URL}/chat/completions  (default primary)
      └── OllamaChatBackend → POST {OLLAMA_BASE_URL}/api/generate     (offline fallback)

Fallback chain: MIMO → Ollama → fail-open ``(True, 0.5, "vl_error:...")``

Backend selection was determined by A/B comparison on 67 cross-page
candidate pairs (2026-07-04):  67.2% agreement rate → MIMO primary.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Prompt
# ═══════════════════════════════════════════════════════════════════════════

PROMPT = """你是一个考试试卷结构分析助手，专门判断试卷跨页内容是否属于同一道题。

下面给出试卷中两个文本片段。文本A是第N页的最后部分，文本B是第N+1页的开头部分。
请判断文本B是文本A的**自然延续**（同一道题跨页，应该合并），还是**一道新题或新内容的开始**（不应该合并）。

## 判断信号（按权重从高到低）

### 强信号（几乎确定）
- 文本B以**主编号**开头（"14."、"第3题"、"二、"后接"选择题"/"填空题"/"解答题"等大题关键词）→ 强烈 no_merge
- 文本B以**【答案】【解析】【详解】【点睛】【分析】【考点】**开头 → 确定 no_merge
- 文本A末尾是选项（A/B/C/D），文本B以下一个选项开头（如A末"C."，B首"D."）→ 确定 merge
- 文本A末尾是**括号填空**（如"（　）"、"_____处"），文本B继续描述 → 确定 merge

### 中等信号
- 文本A在句子/公式/推理中间断开（无句号/问号/感叹号结尾），文本B接续同一主题 → merge
- 文本B以**子编号**开头（"（1）"、"(2)"、"①"、"②"）→ 通常是同一题的子问题 → merge
- 文本B是选项的延续（如A末"D. 以上都不对"后B首新的分析文本）→ 需结合上下文

### 弱信号
- 文本A和B的关键词/主题有交集 → 倾向 merge
- 文本B以"解："、"证明："开头 → 通常是新题的解答 → no_merge
- 文本B以大段公式或新数据开头，与A无语义关联 → 倾向 no_merge

## 判断规则

1. 文本B以独立主编号开头 → no_merge
2. 文本B以解答/答案标记开头（【答案】【解析】【详解】等）→ no_merge
3. 文本B是选项跨页延续（A末选项 → B首选项）→ merge
4. 文本A在句子中间断开，B自然接续 → merge
5. 文本B以子编号开头（（1）(2)等），属于同一题 → merge
6. 文本A以句号/问号/感叹号结尾，且B以全新主题/编号开头 → no_merge

## 示例

**示例1：选项跨页 → merge**
A: "...C. 向上运动　　D."
B: "向左运动"
→ {{"decision": "merge", "confidence": 0.95, "reason": "选项跨页延续，A末尾是D选项开头"}}

**示例2：新题开始 → no_merge**
A: "...故选A。"
B: "14. 已知函数f(x)=x²-2x+1，求f(x)的最小值。"
→ {{"decision": "no_merge", "confidence": 0.95, "reason": "B以主编号14.开头，是新题"}}

**示例3：解析区开始 → no_merge**
A: "...所以答案是B。"
B: "【解析】本题考查的是二次函数的性质..."
→ {{"decision": "no_merge", "confidence": 0.98, "reason": "B以【解析】标记开头，是解答区块"}}

---

文本A（第N页末尾）:
{text_a}

文本B（第N+1页开头）:
{text_b}

请只返回JSON，不要其他内容：
{{"decision": "merge" | "no_merge", "confidence": 0.0-1.0, "reason": "简短理由（引用具体信号）"}}"""


# ═══════════════════════════════════════════════════════════════════════════
# Backend interface
# ═══════════════════════════════════════════════════════════════════════════

class _ChatBackend(ABC):
    """Synchronous chat backend interface."""

    @abstractmethod
    def chat(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> str:
        """Send prompt, return raw response text."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# MIMO backend
# ═══════════════════════════════════════════════════════════════════════════

class MIMOChatBackend(_ChatBackend):
    """Synchronous MIMO /chat/completions backend.

    Uses ``response_format: json_object`` to suppress the reasoning
    (think) phase — without it, MIMO consumes all tokens on internal
    reasoning and returns empty ``content``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "mimo-v2.5",
        timeout: float = 15.0,
    ):
        self._base_url = base_url or settings.MIMO_BASE_URL
        self._api_key = api_key or settings.MIMO_API_KEY
        self._model = model
        self._timeout = timeout

    def chat(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> str:
        """POST /chat/completions → response.choices[0].message.content."""
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": 2048,  # headroom over reasoning phase
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "api-key": self._api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "choices" not in data:
            logger.warning("MIMO response missing 'choices': %s", data)
            return ""

        msg = data["choices"][0].get("message", {})
        # content is primary; reasoning_content is fallback for models
        # that put the answer there (MIMO without json_object)
        return msg.get("content", "") or msg.get("reasoning_content", "")


# ═══════════════════════════════════════════════════════════════════════════
# Ollama backend
# ═══════════════════════════════════════════════════════════════════════════

class OllamaChatBackend(_ChatBackend):
    """Synchronous Ollama /api/generate backend.

    Offline fallback — activated only when MIMO is unreachable.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str = "qwen2.5vl:3b",
        timeout: float = 15.0,
    ):
        self._base_url = base_url or settings.OLLAMA_BASE_URL
        self._model = model
        self._timeout = timeout

    def chat(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> str:
        """POST /api/generate → response["response"]."""
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        return data.get("response", "")


# ═══════════════════════════════════════════════════════════════════════════
# Main verifier
# ═══════════════════════════════════════════════════════════════════════════

class CrossPageVLVerifier:
    """Synchronous VL verifier for cross-page merge decisions.

    Acts as a **false-positive filter**: only called when
    ``_should_merge`` returns ``True`` (~3 calls / PDF).

    Fallback chain: iterate ``backends`` → first success → parse JSON.
    If all backends fail → fail-open: return ``(True, 0.5, reason)``
    (preserves existing text-rules behavior rather than dropping
    potentially valid merges).

    Usage::

        verifier = CrossPageVLVerifier()              # MIMO → Ollama → fail-open
        verifier = CrossPageVLVerifier(backends=["ollama"])  # local only
        should_merge, confidence, reason = verifier.verify_merge(tail_text, head_text)
    """

    # Backend factory — registry for extensibility
    _BACKEND_FACTORY: dict[str, type[_ChatBackend]] = {
        "mimo": MIMOChatBackend,
        "ollama": OllamaChatBackend,
    }

    def __init__(
        self,
        backends: list[str] | None = None,
        mimo_base_url: str | None = None,
        mimo_api_key: str | None = None,
        ollama_base_url: str | None = None,
        ollama_model: str = "qwen2.5vl:3b",
        timeout: float = 15.0,
        max_chars: int = 200,
    ):
        """
        Args:
            backends: Ordered backend names, e.g. ``["mimo", "ollama"]``.
                      Default from A/B comparison (2026-07-04): MIMO primary.
            timeout: Per-backend HTTP timeout in seconds.
            max_chars: Max chars to take from text_a tail / text_b head.
        """
        backend_names = backends if backends is not None else ["mimo", "ollama"]

        self._backends: list[_ChatBackend] = []
        for name in backend_names:
            if name == "mimo":
                self._backends.append(
                    MIMOChatBackend(
                        base_url=mimo_base_url,
                        api_key=mimo_api_key,
                        timeout=timeout,
                    )
                )
            elif name == "ollama":
                self._backends.append(
                    OllamaChatBackend(
                        base_url=ollama_base_url,
                        model=ollama_model,
                        timeout=timeout,
                    )
                )
            else:
                logger.warning("Unknown backend '%s' — skipped", name)

        self._timeout = timeout
        self._max_chars = max_chars

    # ── Public API ──────────────────────────────────────────────────────

    def verify_merge(self, text_a: str, text_b: str) -> tuple[bool, float, str]:
        """Check whether *text_b* is a natural continuation of *text_a*.

        Args:
            text_a: Tail text from candidate A (preceding page).
            text_b: Head text from candidate B (following page).

        Returns:
            ``(should_merge, confidence, reason_string)`` tuple.
            On total failure returns ``(True, 0.5, "vl_error: ...")``
            (fail-open — preserve existing text-rules merge).
        """
        # 1. Truncate
        tail = text_a[-self._max_chars:] if len(text_a) > self._max_chars else text_a
        head = text_b[:self._max_chars] if len(text_b) > self._max_chars else text_b

        if not tail.strip() or not head.strip():
            return True, 0.5, "vl_skip: empty input"

        # 2. Build prompt
        prompt = PROMPT.format(text_a=tail, text_b=head)

        # 3. Try backends in order
        last_error = ""
        for backend in self._backends:
            try:
                raw = backend.chat(prompt)
                if not raw or not raw.strip():
                    last_error = f"empty response from {backend.__class__.__name__}"
                    continue

                parsed = self._parse_response(raw)
                if not parsed:
                    last_error = f"unparseable response from {backend.__class__.__name__}"
                    continue

                decision = parsed.get("decision", "")
                confidence = float(parsed.get("confidence", 0.5))
                reason = parsed.get("reason", "")

                should_merge = decision == "merge"
                return should_merge, confidence, reason

            except httpx.HTTPError as exc:
                last_error = f"{backend.__class__.__name__}: {exc}"
                logger.warning("VL backend error: %s", last_error)
            except Exception as exc:
                last_error = f"{backend.__class__.__name__}: {exc}"
                logger.warning("VL backend unexpected error: %s", last_error)

        # 4. All backends failed → fail-open
        return True, 0.5, f"vl_error: {last_error}"

    # ── JSON parsing ────────────────────────────────────────────────────

    @staticmethod
    def _repair_truncated_json(raw: str) -> dict:
        """Salvage a truncated JSON object from MIMO's mid-response cutoff.

        MIMO occasionally stops generating mid-JSON (confirmed text + image
        modes).  This extracts the ``decision`` field via regex as a
        last-resort before failing open.

        Returns a dict with at least ``decision`` populated, or empty dict
        if nothing salvageable.
        """
        # Strategy 1: Find "decision": "merge" or "no_merge" in raw text
        m = re.search(r'"decision"\s*:\s*"(merge|no_merge)"', raw)
        if m:
            decision = m.group(1)
            # Try to grab confidence if present
            confidence = 0.5
            cm = re.search(r'"confidence"\s*:\s*([0-9.]+)', raw)
            if cm:
                try:
                    confidence = float(cm.group(1))
                except ValueError:
                    pass
            # Try to grab partial reason (up to the truncation point)
            reason = ""
            rm = re.search(r'"reason"\s*:\s*"([^"]*)', raw)
            if rm:
                reason = rm.group(1) + "…"  # mark truncated
            logger.info(
                "_repair_truncated_json: salvaged decision=%s confidence=%.2f",
                decision, confidence,
            )
            return {"decision": decision, "confidence": confidence, "reason": reason}

        # Strategy 2: Bare keyword match (model didn't even produce JSON)
        if "no_merge" in raw.lower():
            return {"decision": "no_merge", "confidence": 0.4, "reason": "salvaged from bare text"}
        if '"merge"' in raw or 'merge' in raw.lower():
            return {"decision": "merge", "confidence": 0.4, "reason": "salvaged from bare text"}

        return {}

    @staticmethod
    def _parse_response(raw: str) -> dict:
        """Extract decision/confidence/reason from raw VL output.

        Delegates to ``VLClient.parse_json`` for robust parsing
        (think-tag stripping, code-fence extraction, 7-layer fallback).
        Falls back to ``_repair_truncated_json`` when MIMO cuts off
        mid-response.
        """
        # Lazy import to avoid circular dependency at module level
        from app.domains.document.parallel_extraction._vl_client import VLClient

        parsed = VLClient.parse_json(raw)
        if not parsed:
            # ── Session #26: Salvage truncated JSON ──
            parsed = CrossPageVLVerifier._repair_truncated_json(raw)
            if not parsed:
                return {}

        # Normalize: ensure expected keys exist
        decision = parsed.get("decision", "")
        if decision not in ("merge", "no_merge"):
            # Try fuzzy match
            if "merge" in str(decision).lower():
                decision = "merge"
            elif "no_merge" in str(decision).lower() or "no merge" in str(decision).lower():
                decision = "no_merge"
            else:
                decision = ""

        confidence = parsed.get("confidence", None)
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.5

        return {
            "decision": decision,
            "confidence": confidence,
            "reason": parsed.get("reason", ""),
        }
