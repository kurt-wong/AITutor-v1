"""Seed provider registry into system_configs.

Revision ID: 011_provider_registry
Revises: 010_llm_config
Create Date: 2026-07-11

Adds provider registry, routing, and metadata config keys so the
LLM Gateway can resolve providers dynamically.  The seed values
match the existing hardcoded defaults in router.py — they make the
configuration visible and editable in the Settings UI without
changing runtime behaviour.

Design (Session #58 P0-A, "折中方案"):
- Provider CLASSES stay fixed (DeepSeek/MIMO/Ollama/Qwen-VL)
- Provider METADATA (label, models, default_model) is DB-configurable
- Mode→provider ROUTING is DB-configurable
- The frontend fetches available-provider lists from the API
"""

from typing import Sequence, Union

from alembic import op

revision: str = "011_provider_registry"
down_revision: Union[str, None] = "010_llm_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO system_configs (config_key, config_value, description, updated_at) VALUES
        -- Provider registry: which providers are enabled
        ('llm.providers.text',     '["deepseek", "mimo"]',
         'Enabled text providers (JSON array of provider IDs)',            NOW()),
        ('llm.providers.vision',   '["mimo-vision", "deepseek-vl", "qwen-vl"]',
         'Enabled vision providers (JSON array of provider IDs)',          NOW()),

        -- Mode → provider routing (overrides hardcoded MODE_TO_PROVIDER)
        ('llm.routing.fast',       'mimo',
         'Provider for fast-answer mode',                                   NOW()),
        ('llm.routing.reasoning',  'deepseek',
         'Provider for reasoning mode',                                     NOW()),
        ('llm.routing.tutor',      'deepseek',
         'Provider for tutor mode',                                         NOW()),
        ('llm.routing.vision',     'mimo-vision',
         'Provider for vision mode',                                        NOW()),

        -- Provider metadata: display label, available models, default model
        ('llm.deepseek.label',         'DeepSeek (深度推理)',
         'Display label for DeepSeek provider',                             NOW()),
        ('llm.deepseek.models',        '["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner", "deepseek-chat"]',
         'Available DeepSeek models (JSON array)',                          NOW()),
        ('llm.deepseek.default_model', 'deepseek-v4-flash',
         'Default model for DeepSeek',                                      NOW()),

        ('llm.mimo.label',         'MIMO (快速推理)',
         'Display label for MIMO provider',                                 NOW()),
        ('llm.mimo.models',        '["mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-flash"]',
         'Available MIMO models (JSON array)',                              NOW()),
        ('llm.mimo.default_model', 'mimo-v2.5-pro',
         'Default model for MIMO',                                          NOW()),

        ('llm.mimo-vision.label',         'MIMO Vision v2.5',
         'Display label for MIMO Vision provider',                          NOW()),
        ('llm.mimo-vision.models',        '["mimo-v2.5"]',
         'Available MIMO Vision models (JSON array)',                       NOW()),
        ('llm.mimo-vision.default_model', 'mimo-v2.5',
         'Default model for MIMO Vision',                                   NOW()),

        ('llm.deepseek-vl.label',         'DeepSeek-VL',
         'Display label for DeepSeek VL provider',                          NOW()),
        ('llm.deepseek-vl.models',        '["deepseek-vl"]',
         'Available DeepSeek VL models (JSON array)',                       NOW()),
        ('llm.deepseek-vl.default_model', 'deepseek-vl',
         'Default model for DeepSeek VL',                                   NOW()),

        ('llm.qwen-vl.label',         'Qwen-VL (DashScope)',
         'Display label for Qwen-VL provider',                              NOW()),
        ('llm.qwen-vl.models',        '["qwen-vl-max", "qwen-vl-plus"]',
         'Available Qwen-VL models (JSON array)',                           NOW()),
        ('llm.qwen-vl.default_model', 'qwen-vl-max',
         'Default model for Qwen-VL',                                       NOW())
        ON CONFLICT (config_key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM system_configs
        WHERE config_key IN (
            'llm.providers.text', 'llm.providers.vision',
            'llm.routing.fast', 'llm.routing.reasoning',
            'llm.routing.tutor', 'llm.routing.vision',
            'llm.deepseek.label', 'llm.deepseek.models', 'llm.deepseek.default_model',
            'llm.mimo.label', 'llm.mimo.models', 'llm.mimo.default_model',
            'llm.mimo-vision.label', 'llm.mimo-vision.models', 'llm.mimo-vision.default_model',
            'llm.deepseek-vl.label', 'llm.deepseek-vl.models', 'llm.deepseek-vl.default_model',
            'llm.qwen-vl.label', 'llm.qwen-vl.models', 'llm.qwen-vl.default_model'
        )
    """)
