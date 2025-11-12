# Nexus — Notion-first Ingestion

### Purpose

Use Notion as the UI and database. Nexus runs simple plugins that ingest external content, generate summaries, and write structured entries to Notion. YouTube videos, news articles, and Hacker News stories are summarized with LLM.

### Principles

- **Simplicity first**: Prefer straightforward solutions over complex abstractions.
- **Single source of truth**: Notion for data; local SQLite only for queue/dedupe.
- **No multi-fallback methods**: Each plugin uses one clear approach; on failure, log and stop.
- **Idempotent operations**: Upserts by canonical URL or stable ID; safe to re-run.
- **Minimal schema**: Let Notion views do the heavy lifting; avoid over-engineering.
- **Clear documentation**: Inputs/outputs, commands, and statuses documented for humans and LLMs.
- **Manual-first**: Run on demand or daily scheduled; no complex orchestration.
- **Basic testing only**: Test our code paths; don't test third-party libraries or network calls.
- **No premature optimization**: Skip retry logic, rate limiting, parallel processing until proven necessary.
- **Fail fast**: Errors stop execution and log clearly; no silent failures or complex recovery.

### Notion schema (minimal)

Three separate databases with distinct purposes:

- YouTube (database) — video content only
  - Name (title)
  - Link (url)
  - Thumbnail (url) — video thumbnail image
  - Summary (rich text) — LLM-generated summary with takeaways and key quotes
  - Source (rich text) — channel name
  - Published (date)
  - Last Updated (date)

- Articles (database) — news articles and blog posts
  - Name (title)
  - Link (url)
  - Summary (rich text) — LLM-generated TL;DR and takeaways
  - Body (rich text) — full article text (first 2000 chars)
  - Source (rich text) — site name
  - Published (date)
  - Last Updated (date)

- Ingestion Log (database) — operational logging
  - Name (title)
  - Time (date)
  - Item URL (url)
  - Action (select: discover | fetch | summarize | write)
  - Result (select: ok | skip | error)
  - Message (rich text)

### Configuration

- `config/notion.json`: `{ youtube_db_id, articles_db_id, log_db_id, parent_page_id }` (token in env/keychain)
- `config/feeds.yaml`: `youtube_use_api: true`, `youtube_channels: []`, `rss_feeds: []`
- `config/summarize.yaml`: `{ model, max_tokens, style }`

### Plugins (single-method)

- YouTube (summarized)
  - Discover: YouTube Data API (preferred), subscription RSS feed, or individual channel RSS
  - Fetch: `youtube-transcript-api` for transcripts, `yt-dlp` for metadata
  - Summarize: LLM (gpt-4o-mini default, chunked if needed, 60s timeout)
  - Write: `upsert_video()` to YouTube database (no Body field)
- News (summarized)
  - Discover: RSS via `feedparser`
  - Fetch: `trafilatura` extraction
  - Summarize: LLM TL;DR + takeaways (60s timeout)
  - Write: `upsert_article()` to Articles database (includes Body field)
- Hacker News (summarized)
  - Discover: HackerNews Firebase API for top stories (score >= 100, last 24h)
  - Fetch: `trafilatura` extraction of linked article
  - Summarize: LLM TL;DR + takeaways with HN discussion link
  - Write: `upsert_article()` to Articles database with source "Hacker News (XXX points)"

### CLI (LLM/Human contract)

- `nexus notion` — bootstrap Notion databases; ensure DBs exist and properties match
- `nexus ingest-youtube [--since 24] [--console]` — ingest YouTube videos from RSS feeds
- `nexus ingest-youtube-url URL [--console] [--dry-run]` — ingest a single YouTube video by URL
- `nexus ingest-news [--since 24] [--console]` — ingest news articles from RSS feeds
- `nexus ingest-hackernews [--min-score 100] [--since 24] [--console] [--workers 10]` — ingest high-scoring HN stories with parallel processing

All commands idempotent; on error, write to Ingestion Log and continue. Use `--console` to print output to screen for debugging.

### Execution flow

1) Discover → enqueue if unseen
2) Fetch → compute Content Hash
3) Summarize (YouTube/News/HN all use LLM)
4) Upsert to Notion Content (and child blocks for body)
5) Log each step to Ingestion Log

### Files & modules

- `plugins/youtube/{collector.py, transcript.py}`
- `plugins/news/{collector.py, extractor.py}`
- `plugins/hackernews/collector.py`
- `tools/{cli.py, notion.py, storage.py, rate_limiter.py, summarizer.py, config.py, text_utils.py}`
- `db/queue.sqlite` (gitignored)
- `docs/{PLAN.md, ops.md}`

### Implementation details

- Python deps: `notion-client`, `feedparser`, `trafilatura`, `youtube-transcript-api`, `openai`, `tenacity`, `pydantic`, `typer`, `python-dateutil`.
- Dedupe: sha256 of normalized content; dedupe by URL/ID.
- Rate limits: throttle Notion writes; backoff on 429.
- Security: env/Keychain for tokens; no secrets in repo.

### Testing (basic)

- Unit tests (no network):
  - URL canonicalization and hashing
  - RSS discovery normalization
  - Transcript/article chunking
  - Summarizer prompt builder (snapshot)
  - Notion client wrapper (mocked)
  - AppleScript wrappers (stubbed)

### Scheduling

- Manual runs via CLI; or daily launchd/cron invoking ingest commands, then summarize pending.

### Human usage

- Adjust feeds in `config/*`
- Use Notion views (Latest, Errors)
- Edit metadata in Notion; re-runs upsert without duplicates

### LLM usage

- Call only the documented CLI commands
- Do not alter schema or configs except `config/*`
- On failure, emit Ingestion Log row and stop

### Limitations

- No alternate fetch fallbacks by principle
- Notion block limits: long bodies stored as paginated blocks
- Async processing with rate limiting for Notion API (3 req/sec)


