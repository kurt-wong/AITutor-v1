"""Seed LLM configuration into system_configs.

Revision ID: 010_llm_config
Revises: 009_knowledge_edges
Create Date: 2026-07-10

Inserts default LLM Gateway configuration rows into system_configs.
These values are used by the LLM Gateway at runtime when the admin
hasn't overridden them via the Settings UI.  The seed values mirror
the existing environment-variable defaults in app/core/config.py.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "010_llm_config"
down_revision: Union[str, None] = "009_knowledge_edges"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO system_configs (config_key, config_value, description, updated_at) VALUES
        ('llm.gateway_mode',        'mock',  'LLM Gateway mode: mock | live',                NOW()),
        ('llm.text_provider',       'mimo',  'Default text provider: deepseek | mimo',       NOW()),
        ('llm.vision_provider',     'mimo-vision', 'Default vision provider: mimo-vision | deepseek-vl | qwen-vl', NOW()),
        ('llm.fast_model',          'mimo-v2.5',     'Model for fast-answer routing',        NOW()),
        ('llm.reasoning_model',     'deepseek-v4-flash', 'Model for reasoning routing',      NOW()),
        ('llm.tutor_model',         'deepseek-v4-flash', 'Model for tutor-mode routing',     NOW()),
        ('llm.vision_model',        'mimo-v2.5',     'Model for vision routing',             NOW()),
        ('llm.deepseek.api_key',    '',      'DeepSeek API key',                              NOW()),
        ('llm.deepseek.base_url',   'https://api.deepseek.com/v1', 'DeepSeek API base URL',  NOW()),
        ('llm.mimo.api_key',        '',      'MIMO API key',                                  NOW()),
        ('llm.mimo.base_url',       'https://api.xiaomimimo.com/v1', 'MIMO API base URL',     NOW()),
        ('llm.qwen_vl.api_key',     '',      'Qwen-VL (DashScope) API key',                  NOW()),
        ('llm.qwen_vl.base_url',    'https://dashscope.aliyuncs.com/compatible-mode/v1', 'Qwen-VL API base URL', NOW()),
        ('llm.ollama.base_url',     'http://localhost:11434', 'Ollama server URL (PC IP)',    NOW()),
        ('llm.ollama.text_model',   'qwen2.5:7b', 'Ollama text model for fallback',          NOW()),
        ('llm.vibethinker.model',   'vibethinker-3b:q8_0', 'VibeThinker model name',         NOW()),
        ('llm.vibethinker.timeout', '300',   'VibeThinker generation timeout (seconds)',     NOW())
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM system_configs WHERE config_key LIKE 'llm.%'
    """)
