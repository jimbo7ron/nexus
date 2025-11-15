# Nexus — Content Ingestion & Knowledge Base

This project ingests external content and stores it locally or in Notion. YouTube videos, news articles, and Hacker News stories are summarized with LLM.

## Storage Backends

Nexus supports two storage backends:

1. **SQLite (Default & Recommended)**: Local-first database with no external dependencies
   - No API token required
   - Faster performance
   - No rate limits
   - Works offline
   - Built-in web UI (coming soon)

2. **Notion**: Cloud-based workspace integration
   - Requires Notion API token
   - Web-based UI via Notion
   - Subject to API rate limits
   - Useful for existing Notion workflows

Configure your backend in `config/writer.json` (see Configuration section below).

## Important Note on Notion Python Client

The official `notion-client` Python library has a bug where it silently drops the `properties` parameter during database creation. This project works around this by using raw HTTP requests via the `requests` library when creating databases. This ensures all database properties (columns) are created correctly.

## Requirements
- Python 3.9+
- Network access for fetching feeds, articles, and transcripts
- (Optional) OpenAI API key for LLM summarization
- (Optional) Notion workspace with internal integration (only if using Notion backend)

## Install
```bash
cd /Users/jammor/Developer/nexus
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
chmod +x ./nexus
```

## Environment

### Quick Start (SQLite Backend - Recommended)

For the default SQLite backend, you only need an OpenAI API key for summarization:
```bash
export OPENAI_API_KEY="sk-..."
```

That's it! You can start ingesting content immediately. No Notion token required.

### Notion Backend (Optional)

If you prefer to use Notion as your backend, also export your Notion token:
```bash
export NOTION_TOKEN="secret_..."
export OPENAI_API_KEY="sk-..."
```

## Configure

### Backend Selection

Configure your storage backend in `config/writer.json`:

**SQLite (Default - Recommended)**:
```json
{
  "backend": "sqlite",
  "db_path": null
}
```
- `db_path: null` uses the default location: `db/nexus.sqlite`
- Or specify a custom path: `"db_path": "/path/to/custom.db"`

**Notion**:
```json
{
  "backend": "notion"
}
```
- Requires `NOTION_TOKEN` environment variable
- Requires running `./nexus notion --parent-page-id <YOUR_PAGE_ID>` first

### Feed Configuration

Edit `config/feeds.yaml` to configure content sources (applies to both backends).

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
### Summarization Configuration

Copy from example and customize:
```bash
cp config/summarize.yaml.example config/summarize.yaml
```
- Set `OPENAI_API_KEY` environment variable for LLM summarization
- Edit `config/summarize.yaml` to customize model, tokens, etc.

## Getting Started

### Option 1: SQLite Backend (Recommended - Simpler Setup)

1. **Install dependencies** (see Install section above)
2. **Set OpenAI API key**:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```
3. **Ensure SQLite backend is configured** in `config/writer.json`:
   ```json
   {
     "backend": "sqlite",
     "db_path": null
   }
   ```
4. **Configure feeds** in `config/feeds.yaml`
5. **Start ingesting**:
   ```bash
   ./nexus ingest-youtube --since 24 --console
   ./nexus ingest-hackernews --min-score 100 --since 24 --console
   ```

Your content will be stored in `db/nexus.sqlite`. No additional setup required!

### Option 2: Notion Backend

1. **Install dependencies** (see Install section above)
2. **Set environment variables**:
   ```bash
   export NOTION_TOKEN="secret_..."
   export OPENAI_API_KEY="sk-..."
   ```
3. **Configure Notion backend** in `config/writer.json`:
   ```json
   {
     "backend": "notion"
   }
   ```
4. **Bootstrap Notion databases**:
   ```bash
   ./nexus notion --parent-page-id <YOUR_NOTION_PAGE_ID>
   ```
   This creates three databases in Notion:
   - **YouTube**: Video content with thumbnails and LLM summaries
   - **Articles**: News articles and blog posts with LLM summaries and full text
   - **Ingestion Log**: Operational logging for all ingestion activities
5. **Configure feeds** in `config/feeds.yaml`
6. **Start ingesting**:
   ```bash
   ./nexus ingest-youtube --since 24 --console
   ./nexus ingest-hackernews --min-score 100 --since 24 --console
   ```

### Migrating from Notion to SQLite

If you have existing data in Notion and want to migrate to SQLite:

```bash
./nexus migrate
```

This will export all your videos, articles, and logs from Notion and import them into SQLite. See `docs/MIGRATION.md` for detailed instructions.

## Test YouTube API (Optional)
Before running the full ingestion, test that YouTube API authentication works:
```bash
.venv/bin/python test_youtube_auth.py
```
This will:
- Open a browser for OAuth authorization (first time only)
- Fetch and display your subscriptions
- Save the authentication token for future use

## Ingestion Commands

YouTube and Hacker News ingestion work with both SQLite and Notion backends (configured in `config/writer.json`). News ingestion currently requires the Notion backend (the CLI warns if SQLite is selected).

### YouTube Videos
Discover via RSS or API, fetch transcript, summarize, and store:
```bash
./nexus ingest-youtube --since 24 [--console] [--verbose] [--workers 10]
```
Note: If `youtube_use_api: true` in config/feeds.yaml, this will use the YouTube Data API to automatically fetch videos from all your subscriptions.

Single video by URL:
```bash
./nexus ingest-youtube-url --url "https://youtu.be/VIDEO_ID" [--console] [--dry-run]
```

### News Articles
RSS feeds → extract with trafilatura → summarize → store:
```bash
./nexus ingest-news --since 24 [--console]
```
Note: Currently only works with Notion backend. SQLite support coming soon.

### Hacker News Stories
Top stories → extract article → summarize → store:
```bash
./nexus ingest-hackernews --min-score 100 --since 24 [--console] [--verbose] [--workers 10]
```

### Notes
- **Deduplication**: The system writes a content hash locally (`db/queue.sqlite`) and skips items that haven't changed
- **Summaries**: Content is automatically summarized using the configured LLM (OpenAI by default)
- **Parallel Processing**: YouTube and HackerNews ingestion support concurrent workers (default: 10)
- **Console Output**: Use `--console` flag to see real-time progress and summaries

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
cp config/summarize.yaml.example config/summarize.yaml
cp env.example .env
```

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

## Documentation
- **Migration Guide**: `docs/MIGRATION.md` - Migrating from Notion to SQLite
- **Plan**: `docs/PLAN.md` - Project architecture and development plan
- **Operations**: `docs/ops.md` - Scheduling and automation
