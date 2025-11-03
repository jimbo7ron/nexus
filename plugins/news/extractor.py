from __future__ import annotations

from typing import Optional

import trafilatura


def fetch_article_text(url: str) -> Optional[str]:
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
    return text


