"""Factory pattern for creating writer instances based on configuration.

This module provides a factory function that creates either a NotionWriter
or DatabaseWriter based on the configuration in config/writer.json.
"""

from __future__ import annotations

from typing import Optional, Union

from notion_client import Client

from .config import WriterConfig, load_notion_config
from .database import DatabaseWriter
from .notion import NotionWriter


def create_writer(
    config: WriterConfig,
    notion_token: Optional[str] = None,
) -> Union[NotionWriter, DatabaseWriter]:
    """Create a writer instance based on configuration.

    Args:
        config: WriterConfig specifying backend and options
        notion_token: Notion API token (required only if backend='notion')

    Returns:
        Either NotionWriter or DatabaseWriter instance

    Raises:
        ValueError: If backend is unknown or required config is missing
    """
    backend = config.backend.lower()

    if backend == "sqlite":
        # Create DatabaseWriter (no token needed)
        return DatabaseWriter(db_path=config.db_path)

    elif backend == "notion":
        # Validate token is provided
        if not notion_token:
            raise ValueError(
                "NOTION_TOKEN is required when backend='notion'. "
                "Set the NOTION_TOKEN environment variable."
            )

        # Load Notion database configuration
        notion_config = load_notion_config()
        if not notion_config.youtube_db_id or not notion_config.articles_db_id or not notion_config.log_db_id:
            raise ValueError(
                "Notion database IDs are not configured. "
                "Run 'nexus notion --parent-page-id <id>' to bootstrap Notion databases."
            )

        # Create Notion client and writer
        client = Client(auth=notion_token)
        return NotionWriter(
            client,
            notion_config.youtube_db_id,
            notion_config.articles_db_id,
            notion_config.log_db_id,
        )

    else:
        raise ValueError(
            f"Unknown backend: '{config.backend}'. "
            f"Valid backends are: 'sqlite', 'notion'"
        )
