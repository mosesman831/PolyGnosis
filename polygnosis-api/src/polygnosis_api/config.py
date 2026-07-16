"""Settings and YAML boardroom config loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POLYGNOSIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_base_url: str = "https://ai-gateway.vercel.sh/v1"
    api_key: str = ""
    default_model: str = "anthropic/claude-sonnet-4"
    config_path: str = str(DEFAULT_CONFIG_PATH)
    artifacts_dir: str = "./artifacts"
    corrections_buffer: str = "./.corrections_buffer.json"
    host: str = "0.0.0.0"
    port: int = 8080


def load_boardroom_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path or Settings().config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text()) or {}
    if "models" not in data or "settings" not in data:
        raise ValueError("config.yaml must contain 'models' and 'settings'")
    return data


def get_solver_model_name(cfg: dict[str, Any], idx: int) -> str:
    solver_list = cfg.get("solver_models") or []
    if solver_list and idx < len(solver_list) and solver_list[idx]:
        return str(solver_list[idx])
    key = f"solver_{idx + 1}"
    model = (cfg.get("models") or {}).get(key, "")
    if model:
        return str(model)
    return str((cfg.get("models") or {}).get("fallback", "") or "")


def get_role_model(cfg: dict[str, Any], role: str) -> str:
    models = cfg.get("models") or {}
    return str(models.get(role) or models.get("fallback") or "")
