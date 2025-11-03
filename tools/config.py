from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Any, Dict

from pydantic import BaseModel, Field
import yaml


CONFIG_DIR = Path(__file__).parent.parent / "config"
NOTION_CONFIG_PATH = CONFIG_DIR / "notion.json"
FEEDS_CONFIG_PATH = CONFIG_DIR / "feeds.yaml"
SUMMARIZE_CONFIG_PATH = CONFIG_DIR / "summarize.yaml"
APPLE_CONFIG_PATH = CONFIG_DIR / "apple.yaml"


class NotionConfig(BaseModel):
    parent_page_id: str = Field(
        default="",
        description="Notion parent page ID under which databases will be created",
    )
    youtube_db_id: str = Field(default="", description="Notion YouTube database ID (video content)")
    articles_db_id: str = Field(default="", description="Notion Articles database ID (news articles and blog posts)")
    notes_db_id: str = Field(default="", description="Notion Notes database ID")
    reminders_db_id: str = Field(default="", description="Notion Reminders database ID")
    log_db_id: str = Field(default="", description="Notion Ingestion Log database ID")


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_notion_config() -> NotionConfig:
    ensure_config_dir()
    if NOTION_CONFIG_PATH.exists():
        data = json.loads(NOTION_CONFIG_PATH.read_text(encoding="utf-8"))
        return NotionConfig(**data)
    cfg = NotionConfig()
    save_notion_config(cfg)
    return cfg


def save_notion_config(cfg: NotionConfig) -> None:
    ensure_config_dir()
    NOTION_CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")


def get_notion_token() -> Optional[str]:
    return os.environ.get("NOTION_TOKEN")


def _load_yaml(path: Path) -> Dict[str, Any]:
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def load_feeds_config() -> Dict[str, Any]:
    return _load_yaml(FEEDS_CONFIG_PATH)


def load_apple_config() -> Dict[str, Any]:
    return _load_yaml(APPLE_CONFIG_PATH)


def load_summarize_config() -> Dict[str, Any]:
    cfg = _load_yaml(SUMMARIZE_CONFIG_PATH)
    if not cfg:
        # Return defaults if missing
        return {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "max_tokens": 1000,
            "temperature": 0.3,
            "chunk_size": 8000,
            "api_key_env": "OPENAI_API_KEY",
        }
    return cfg


