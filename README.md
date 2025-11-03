# Nexus — Notion-first Ingestion

This project ingests external content into Notion. YouTube videos and news articles are summarized; Apple Notes and Apple Reminders are stored without summaries. Notion is the single source of truth and UI.

## Important Note on Notion Python Client

The official `notion-client` Python library has a bug where it silently drops the `properties` parameter during database creation. This project works around this by using raw HTTP requests via the `requests` library when creating databases. This ensures all database properties (columns) are created correctly.

## Requirements
- macOS (for Apple Notes/Reminders via AppleScript)
- Python 3.9+
- Notion workspace with an internal integration (Notion API token)
- Network access for fetching feeds, articles, and transcripts

## Install
```bash
cd /Users/jammor/Developer/nexus
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
chmod +x ./nexus
```

## Environment
- Export your Notion token and OpenAI API key before running commands:
```bash
export NOTION_TOKEN="secret_..."
export OPENAI_API_KEY="sk-..."
```

## Configure
- Notion IDs (written by bootstrap):
  - `config/notion.json` contains:
    - `parent_page_id`: The page under which the databases will live
    - `youtube_db_id`: Filled by bootstrap (video content)
    - `articles_db_id`: Filled by bootstrap (news articles and blog posts)
    - `notes_db_id`: Filled by bootstrap
    - `reminders_db_id`: Filled by bootstrap
    - `log_db_id`: Filled by bootstrap
- Feeds (edit to suit):
  - `config/feeds.yaml`

### YouTube Monitoring Options

**Option 1: YouTube Data API (RECOMMENDED)**

Automatically monitor ALL your subscriptions using the YouTube Data API:

```yaml
# config/feeds.yaml
youtube_use_api: true
youtube_api_max_channels: 100
```

**Setup Steps:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "Nexus YouTube")
3. Enable "YouTube Data API v3"
   - Go to APIs & Services → Library
   - Search for "YouTube Data API v3" → Enable
4. Create OAuth credentials:
   - Go to APIs & Services → Credentials
   - Configure OAuth consent screen:
     - User Type: External
     - App name: "Nexus" (your email)
     - Scopes: Add `https://www.googleapis.com/auth/youtube.readonly`
     - Test users: Add your email
   - Create Credentials → OAuth client ID → Desktop app
   - Download JSON file
5. Save the downloaded file as: `config/youtube_client_secret.json`
6. First run will open browser for OAuth authorization

**Option 2: Subscription RSS Feed** (if you can find it)

```yaml
youtube_subscription_feed: https://www.youtube.com/feeds/videos.xml?channel_id=YOUR_CHANNEL_ID
```
Note: YouTube has made this harder to find. The RSS icon may not appear for all users.

**Option 3: Manual Channel List**

```yaml
youtube_channels:
  - UC_x5XG1OV2P6uZZ5FSM9Ttw  # individual channel IDs
```

### Other Feeds

```yaml
rss_feeds:
  - https://ai.googleblog.com/feeds/posts/default
  - https://news.ycombinator.com/rss
```
- Apple integration (optional):
  - `config/apple.yaml`
```yaml
notes_folder: "Nexus"       # Notes folder to ingest
reminders_list: "Nexus"     # Reminders list to ingest
```
- Summarization (copy from example):
  - `cp config/summarize.yaml.example config/summarize.yaml`
  - Set `OPENAI_API_KEY` environment variable for LLM summarization
  - Edit `config/summarize.yaml` to customize model, tokens, etc.

## Bootstrap Notion
Create the databases (YouTube, Articles, Notes, Reminders, Ingestion Log) and record their IDs in `config/notion.json`.
```bash
./nexus notion --parent-page-id <YOUR_NOTION_PAGE_ID>
```

This creates five separate databases:
- **YouTube**: Video content with thumbnails and LLM summaries (no Body field)
- **Articles**: News articles and blog posts with LLM summaries and full text
- **Notes**: Apple Notes stored without summarization
- **Reminders**: Apple Reminders stored without summarization
- **Ingestion Log**: Operational logging for all ingestion activities

## Test YouTube API (Optional)
Before running the full ingestion, test that YouTube API authentication works:
```bash
.venv/bin/python test_youtube_auth.py
```
This will:
- Open a browser for OAuth authorization (first time only)
- Fetch and display your subscriptions
- Save the authentication token for future use

## Run ingestion
- YouTube (discover via RSS or API, fetch transcript, summarize, upsert into Notion):
```bash
./nexus ingest-youtube --since 24 [--console]
```
Note: If `youtube_use_api: true` in config/feeds.yaml, this will use the YouTube Data API to automatically fetch videos from all your subscriptions.
— Single video (URL), console preview and optional Notion write:
```bash
./nexus ingest-youtube-url --url "https://youtu.be/VIDEO_ID" --console [--dry-run]
```
- News (RSS → extract with trafilatura → summarize → upsert):
```bash
./nexus ingest-news --since 24 [--console]
```
- Apple Notes (no summary; upsert by synthetic URL `notes://<id>`):
```bash
./nexus ingest-apple-notes [--console]
```
- Apple Reminders (no summary; upsert by synthetic URL `reminders://<id>`):
```bash
./nexus ingest-apple-reminders [--console]
```

Notes:
- Dedupe: the system writes a content hash locally (`db/queue.sqlite`) and skips items that haven't changed.
- Status field: videos/articles are marked `summarized` after LLM processing; Apple items are `fetched`.
- Summaries: YouTube/news items are automatically summarized using the configured LLM (OpenAI by default).
- Backfill: if items were ingested without summaries (Status=fetched), run `./nexus summarize --limit 50` to process them.

## Scheduling (optional)
Run daily via launchd. Example plist and details are in `docs/ops.md`.

## Tests
```bash
source .venv/bin/activate
python -m pytest -q
```

## Troubleshooting

### Missing Notion Token
Ensure `NOTION_TOKEN` is exported in your shell:
```bash
export NOTION_TOKEN=secret_...
```
Or add to `.env` and source it.

### Notion DB IDs Missing
Run the bootstrap command:
```bash
./nexus notion --parent-page-id YOUR_PAGE_ID
```

### Could Not Access Notion Databases
- Verify your token is valid
- Check the integration has access to the parent page
- Re-run `./nexus notion` to recreate databases

### YouTube API Authentication
If you get OAuth errors:
- Ensure `config/youtube_client_secret.json` exists (download from Google Cloud Console)
- Delete `config/youtube_token.pickle` to re-authenticate
- Check that your email is added as a test user in OAuth consent screen
- Make sure YouTube Data API v3 is enabled in your Google Cloud project

### YouTube Subscription Feed Not Working
The subscription RSS feed is hard to find. We recommend using the **YouTube Data API** instead (see Configure section).

For RSS feeds:
1. Visit https://www.youtube.com/feed/subscriptions while logged in
2. Use a browser extension like "RSS Feed Reader" to detect the feed
3. Or fall back to monitoring individual channels

### YouTube Transcript Errors
- Video may not have captions/transcripts available
- Video may be private or deleted
- Check for typos in the URL

### Missing Config Files
Copy example files and customize:
```bash
cp config/feeds.yaml.example config/feeds.yaml
cp config/apple.yaml.example config/apple.yaml
cp config/summarize.yaml.example config/summarize.yaml
cp env.example .env
```

### AppleScript Permissions
macOS may prompt to allow Terminal/Python to control Notes/Reminders. Approve in:
**System Settings → Privacy & Security → Automation**

### Module Import Errors
Ensure you're running from the project root:
```bash
cd /Users/jammor/Developer/nexus
./nexus <command>
```

### Python Version Warnings
You may see deprecation warnings from `yt-dlp` or other libraries about Python 3.9. These are suppressed where possible but some warnings from C extensions cannot be filtered. These warnings do not affect functionality and can be safely ignored. To upgrade Python (recommended):
```bash
# Install Python 3.10+ via Homebrew or python.org
# Then recreate the virtual environment:
rm -rf .venv
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Docs
- Plan: `docs/PLAN.md`
- Operations: `docs/ops.md`

