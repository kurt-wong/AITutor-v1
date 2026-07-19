"""
Core Configuration

Centralized config — all values from environment variables.
Supports .env file loading. No hardcoded values.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings — all values loaded from environment variables."""

    APP_NAME: str = "AI Tutor"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str

    # MinIO
    MINIO_URL: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET: str = "ai-tutor"

    # LLM Gateway mode: "mock" | "live"
    LLM_GATEWAY_MODE: str = "mock"

    # DeepSeek API
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    # MIMO API
    MIMO_API_KEY: str = ""
    MIMO_BASE_URL: str = "https://api.xiaomimimo.com/v1"
    MIMO_VISION_MODEL: str = "mimo-v2.5"

    # Vision Model API (Phase 2)
    # DEEPSEEK_VL_ENDPOINT is a documented alias for DEEPSEEK_VL_BASE_URL (DEPLOYMENT-Phase2 §21.2)
    DEEPSEEK_VL_API_KEY: str = ""
    DEEPSEEK_VL_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_VL_ENDPOINT: str = ""  # alias, falls back to DEEPSEEK_VL_BASE_URL if empty
    QWEN_VL_API_KEY: str = ""
    QWEN_VL_MODEL: str = "qwen3.6-plus"  # Session #57: Qwen3.6+ VL multimodal
    QWEN_VL_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_VL_ENDPOINT: str = ""  # alias, falls back to QWEN_VL_BASE_URL if empty

    # OCR Configuration
    OCR_PROVIDER: str = "paddleocr"  # paddleocr | simpletex | vl_model
    OCR_MOCK_MODE: bool = True  # Use mock mode for testing

    # VL OCR Configuration (Phase 3)
    VL_OCR_ENABLED: bool = False  # Enable VL model as primary OCR
    VL_OCR_MODEL: str = "qwen3.6-plus"  # Session #77: Qwen 3.6 Plus cloud (DashScope)
    VL_OCR_CONFIDENCE_THRESHOLD: float = 0.75  # Below this, fallback to legacy OCR

    # VL Fallback Priority (Route B2) — Session #77 updated
    #   Primary: Qwen 3.6 Plus cloud API (DashScope, ~40 tok/s)
    #   Fallback: MIMO V2.5 cloud → Ollama qwen2.5vl:3b local
    VL_PRIMARY: str = "qwen"  # "qwen" | "mimo" | "ollama" — which VL backend to try first

    # VL Model Benchmark (2025-07-16, Session #77):
    #   Qwen 3.6 Plus ⭐ — DashScope cloud API, ~40 tok/s, no local VRAM
    #   MIMO V2.5      — Cloud, reliable for LaTeX extraction (C3b)
    #   qwen2.5vl:3b   — Ollama local, ~6.2GB VRAM, kept as last-resort fallback
    #   qwythos-9b     — ❌ VL 100% broken. REMOVED from VL pipeline.

    # Per-Component VL Model Assignment (C2/C3/C4) — Session #77
    #   C2 (PaddleOCR): 不使用 VL
    #   C4 (Figure bbox): Qwen 3.6 Plus → MIMO V2.5 → Ollama qwen2.5vl:3b
    #   C3a (OCR verify): Qwen 3.6 Plus → MIMO V2.5 → Ollama qwen2.5vl:3b
    #   C3b (LaTeX): MIMO V2.5 唯一方案
    VL_C4_PRIMARY: str = "mimo"        # C4 figure detection backend ("mimo" | "ollama")
    VL_C3_MODEL: str = ""              # C3b model (deprecated — MIMO V2.5 is the only working backend)
    VL_C3B_PRIMARY: str = "mimo"       # "mimo" — C3b LaTeX extraction; Ollama path removed (qwythos VL broken)

    # Extraction Quality Gate Thresholds (Route B2)
    EXTRACTION_MIN_COVERAGE: float = 0.30
    EXTRACTION_MIN_CONFIDENCE_RATIO: float = 0.50
    EXTRACTION_CONFIDENCE_THRESHOLD: float = 0.70

    # Parallel Extraction Pipeline (Phase 3 — 4-component architecture)
    PARALLEL_EXTRACTION_ENABLED: bool = True  # Enable parallel pipeline (C1-C4)
    PARALLEL_EXTRACTION_WORKERS: int = 4       # C2 ThreadPoolExecutor max_workers
    PIPELINE_WORKERS: int = 3                  # Number of async pipeline workers
    LLM_VERIFY_CONFIDENCE_THRESHOLD: float = 0.85  # Below this -> [NEED_LLM_VERIFY]
    PARALLEL_EXTRACTION_DPI: int = 200          # Render DPI for page images
    PARALLEL_EXTRACTION_SCAN_THRESHOLD: int = 50  # chars/page below which = scanned

    # PaddleOCR Configuration
    PADDLEOCR_USE_GPU: bool = False
    PADDLEOCR_LANG: str = "ch"  # ch | en

    # SimpleTex Configuration
    SIMPLETEX_API_KEY: str = ""
    SIMPLETEX_API_URL: str = "https://server.simpletex.cn/api/latex_ocr"

    # Embedding Configuration
    EMBEDDING_PROVIDER: str = "ollama"  # ollama | openai
    EMBEDDING_MODEL: str = "qwen3-embedding:4b"
    EMBEDDING_MOCK_MODE: bool = True
    EMBEDDING_DIMENSION: int = 0  # 0 = auto-detect

    # Ollama Configuration
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # VibeThinker — local STEM reasoning model (Session #47 Part B)
    # vibethinker-3b:q8_0: 3.1B params, Q8_0 quant (~3.3GB VRAM)
    # Used for generating detailed explanations for questions without them
    VIBETHINKER_MODEL: str = "vibethinker-3b:q8_0"
    VIBETHINKER_TIMEOUT: int = 300  # seconds — explanations take longer

    # CORS — comma-separated origins. Matches Vite dev server + common local URLs.
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # PaddleOCR-VL API (Phase 2+)
    PADDLEOCR_VL_TOKEN: str = ""
    PADDLEOCR_VL_ENABLED: bool = False
    PADDLEOCR_VL_FORMULA_MODE: str = "api"  # api | vl | hybrid
    PADDLEOCR_VL_LAYOUT_MODE: str = "vl"    # api | vl | both  (Phase 4+)
    PADDLEOCR_VL_API_TIMEOUT: int = 300
    PADDLEOCR_VL_MAX_RETRIES: int = 2

    # LLM Annotation — 一次性标注完整试卷 Markdown（替代逐题正则拆分）
    LLM_ANNOTATION_ENABLED: bool = False  # 启用 LLM 标注管线（metadata + questions JSON）

    # Admin
    ADMIN_API_KEY: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
