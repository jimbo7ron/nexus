"""Extract YouTube video metadata using yt-dlp."""

from __future__ import annotations

import asyncio
import warnings
from typing import Optional
from datetime import datetime

# Suppress Python 3.9 deprecation warnings from yt-dlp and its dependencies
warnings.filterwarnings("ignore", message=".*Support for Python version 3.9 has been deprecated.*")

import yt_dlp


def extract_metadata(url: str) -> dict:
    """
    Extract metadata from a YouTube URL.
    
    Returns dict with: title, channel, published_iso, video_id, thumbnail
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'logger': None,  # Disable logging entirely
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'YouTube Video')
            channel = info.get('uploader', info.get('channel', ''))
            video_id = info.get('id', '')
            published_str = info.get('upload_date')  # Format: YYYYMMDD
            
            # Get highest quality thumbnail
            thumbnail = info.get('thumbnail', '')
            # Prefer maxresdefault or hqdefault if available
            if video_id and not thumbnail:
                thumbnail = f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg'
            
            # Convert upload_date to ISO format
            published_iso = None
            if published_str:
                try:
                    dt = datetime.strptime(published_str, '%Y%m%d')
                    published_iso = dt.isoformat() + 'Z'
                except:
                    pass
            
            return {
                'title': title,
                'channel': channel,
                'video_id': video_id,
                'published_iso': published_iso,
                'thumbnail': thumbnail,
            }
    except Exception as e:
        # Return minimal metadata on error
        return {
            'title': 'YouTube Video',
            'channel': '',
            'video_id': '',
            'published_iso': None,
            'thumbnail': '',
            'error': str(e),
        }


async def extract_metadata_async(url: str) -> dict:
    """Async wrapper for extract_metadata using thread pool."""
    return await asyncio.to_thread(extract_metadata, url)

