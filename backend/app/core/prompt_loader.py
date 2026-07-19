"""
Prompt Loader

Loads prompt templates from YAML files.
Provides system_prompt and schema for each prompt.

Architecture: Prompts are files, never hardcoded in Python code (prompt.md §2 Rule 4).
"""

from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(name: str) -> dict[str, Any]:
    """Load a prompt template by name.

    Returns:
        {
            "name": str,
            "version": str,
            "description": str,
            "provider": str,
            "system_prompt": str,
            "input_schema": dict,
            "output_schema": dict,
            "output_example": str,
        }
    """
    # Prevent path traversal attacks (name must be a simple identifier)
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"Invalid prompt name: {name}")
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid prompt name: {name}")

    file_path = PROMPTS_DIR / f"{name}.yaml"
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {file_path}")

    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data


def get_system_prompt(name: str) -> str:
    """Get the system prompt string for a given prompt name."""
    prompt = load_prompt(name)
    return prompt.get("system_prompt", "")


def format_prompt(name: str, **kwargs) -> str:
    """Format a prompt template with the given variables.

    Replaces {key} placeholders in system_prompt with provided values.
    """
    system_prompt = get_system_prompt(name)
    for key, value in kwargs.items():
        system_prompt = system_prompt.replace(f"{{{key}}}", str(value))
    return system_prompt


def list_prompts() -> list[dict[str, str]]:
    """List all available prompt templates."""
    prompts = []
    for file in sorted(PROMPTS_DIR.glob("*.yaml")):
        if file.name == "prompt_registry.yaml":
            continue
        with open(file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        prompts.append({
            "name": data.get("name", file.stem),
            "version": data.get("version", "1.0"),
            "provider": data.get("provider", "unknown"),
            "description": data.get("description", ""),
        })
    return prompts
