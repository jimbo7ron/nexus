Nexus operations

Environment
- Set NOTION_TOKEN and OPENAI_API_KEY in your shell or .env file

Initial setup
1. Run bootstrap to create databases: `./nexus notion --parent-page-id <PAGE_ID>`
   - This creates 3 databases: YouTube, Articles, Ingestion Log
   - Database IDs are saved to `config/notion.json`
2. Configure feeds in `config/feeds.yaml`:
   - Set `youtube_use_api: true` for automatic subscription monitoring (recommended)
   - Or configure `youtube_channels` or `youtube_subscription_feed`
   - Add `rss_feeds` for news articles

Manual runs
- `./nexus ingest-youtube --since 24 [--console]` — ingest from all subscriptions (or configured feeds)
- `./nexus ingest-youtube-url <URL> [--console]` — ingest a single video by URL
- `./nexus ingest-news --since 24 [--console]` — ingest news articles from RSS feeds
- `./nexus ingest-hackernews --min-score 100 --since 24 [--console] [--workers 10]` — ingest high-scoring HN stories with parallel processing

Note: Each content type has its own database and upsert method:
- Videos → YouTube database (upsert_video, no Body field)
- Articles → Articles database (upsert_article, includes Body field)
- HN Stories → Articles database (upsert_article, with HN discussion link and score in summary)

launchd example (daily at 7:30)
Save to `~/Library/LaunchAgents/nexus.ingest.plist`:

<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.nexus.ingest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/jammor/Developer/nexus/nexus</string>
    <string>ingest-news</string>
    <string>--since</string>
    <string>24</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>NOTION_TOKEN</key>
    <string>your_token_here</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>7</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>/Users/jammor/Developer/nexus</string>
  <key>StandardOutPath</key>
  <string>/Users/jammor/Developer/nexus/logs/ingest.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/jammor/Developer/nexus/logs/ingest.err.log</string>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>

Load:
- `launchctl load ~/Library/LaunchAgents/nexus.ingest.plist`


