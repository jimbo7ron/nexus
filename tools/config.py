from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Any, Dict

from pydantic import BaseModel, Field
import yaml


CONFIG_DIR = Path(__file__).parent.parent / "config"
NOTION_CONFIG_PATH = CONFIG_DIR / "notion.json"
WRITER_CONFIG_PATH = CONFIG_DIR / "writer.json"
FEEDS_CONFIG_PATH = CONFIG_DIR / "feeds.yaml"
SUMMARIZE_CONFIG_PATH = CONFIG_DIR / "summarize.yaml"


class NotionConfig(BaseModel):
    parent_page_id: str = Field(
        default="",
        description="Notion parent page ID under which databases will be created",
    )
    youtube_db_id: str = Field(default="", description="Notion YouTube database ID (video content)")
    articles_db_id: str = Field(default="", description="Notion Articles database ID (news articles and blog posts)")
    log_db_id: str = Field(default="", description="Notion Ingestion Log database ID")


class WriterConfig(BaseModel):
    """Configuration for the writer backend (sqlite or notion)."""
    backend: str = Field(
        default="sqlite",
        description="Backend to use for content storage: 'sqlite' or 'notion'",
    )
    db_path: Optional[Path] = Field(
        default=None,
        description="Path to SQLite database file (only used when backend='sqlite')",
    )


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


def load_writer_config() -> WriterConfig:
    """Load writer configuration from config/writer.json.

    Returns:
        WriterConfig with backend and db_path settings
    """
    ensure_config_dir()
    if WRITER_CONFIG_PATH.exists():
        data = json.loads(WRITER_CONFIG_PATH.read_text(encoding="utf-8"))
        # Handle db_path as string and convert to Path
        if "db_path" in data and data["db_path"]:
            data["db_path"] = Path(data["db_path"])
        return WriterConfig(**data)
    # Create default config if missing
    cfg = WriterConfig()
    save_writer_config(cfg)
    return cfg


def save_writer_config(cfg: WriterConfig) -> None:
    """Save writer configuration to config/writer.json.

    Args:
        cfg: WriterConfig to save
    """
    ensure_config_dir()
    # Convert Path to string for JSON serialization
    data = cfg.model_dump()
    if data.get("db_path"):
        data["db_path"] = str(data["db_path"])
    WRITER_CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


