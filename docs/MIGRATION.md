# Migration Guide: Notion to SQLite

This guide walks you through migrating your existing Nexus content from Notion to the local SQLite database.

## Table of Contents
- [Why Migrate?](#why-migrate)
- [Prerequisites](#prerequisites)
- [Migration Process](#migration-process)
- [Verification](#verification)
- [Switching Backends](#switching-backends)
- [Rollback](#rollback)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

## Why Migrate?

Migrating from Notion to SQLite offers several benefits:

1. **Local-First**: Your data stays on your machine. No cloud dependency.
2. **Faster Performance**: Direct database access is significantly faster than API calls.
3. **No Rate Limits**: Notion's API has rate limits that can slow down ingestion. SQLite has none.
4. **No Token Required**: No need to manage Notion integration tokens or worry about expiration.
5. **Offline Access**: Works without internet connection (except for fetching new content).
6. **Better Control**: Full control over your data with standard SQL queries.
7. **Cost**: SQLite is free. Large Notion workspaces may incur costs.

The migration is **safe** and **reversible**. Your Notion data remains unchanged, and you can switch back at any time.

## Prerequisites

Before you begin, ensure you have:

1. **Notion Access**: Your `NOTION_TOKEN` environment variable must be set
   ```bash
   export NOTION_TOKEN="secret_..."
   ```

2. **Notion Databases**: Your Notion databases must be properly configured
   - `config/notion.json` should contain valid database IDs
   - If not configured, run: `./nexus notion --parent-page-id <YOUR_PAGE_ID>`

3. **Disk Space**: Ensure you have sufficient disk space for the SQLite database
   - Estimate: ~1KB per video/article on average
   - Example: 10,000 items = ~10MB

4. **Backup (Optional but Recommended)**:
   - Your Notion data is not modified during migration
   - However, if you have an existing `db/nexus.sqlite`, consider backing it up:
     ```bash
     cp db/nexus.sqlite db/nexus.sqlite.backup
     ```

## Migration Process

The migration is designed to be simple and safe. It takes 3 steps:

### Step 1: Verify Current Setup

Check that your Notion backend is properly configured:

```bash
# Verify environment variable
echo $NOTION_TOKEN

# Check config
cat config/notion.json
```

You should see database IDs for YouTube, Articles, and Ingestion Log.

### Step 2: Run Migration

Execute the migration command:

```bash
./nexus migrate
```

You'll see a confirmation prompt explaining what will happen:

```
Migration: Notion → SQLite

This will:
  1. Export all videos, articles, and logs from Notion
  2. Import them into db/nexus.sqlite
  3. Preserve existing SQLite data (upsert only)

Note: This may take several minutes and will make many Notion API calls.

Do you want to proceed? [y/N]:
```

Type `y` and press Enter to proceed.

**Skip Confirmation (Automation)**:
```bash
./nexus migrate --yes
```

### Step 3: Monitor Progress

The migration provides real-time feedback:

```
Nexus Migration: Notion → SQLite

Initializing SQLite database...
✓ Exported 1,247 videos
✓ Exported 583 articles
✓ Exported 1,830 log entries

Importing into SQLite...
✓ Imported 1,247 videos
✓ Imported 583 articles
✓ Imported 1,830 log entries

Verifying migration...
✓ Database contains 1,247 videos
✓ Database contains 583 articles

Migration Complete!
Database location: /path/to/nexus/db/nexus.sqlite
```

**Duration**: Expect 2-5 minutes for every 1,000 items, depending on:
- Notion API response times
- Network speed
- Database size

**Safety Notes**:
- The migration is **idempotent**: Safe to run multiple times
- Existing SQLite data is preserved (upsert, not overwrite)
- Your Notion databases are **read-only** during migration (no modifications)
- If migration fails, you can simply retry

## Verification

After migration completes, verify your data:

### 1. Check Database File

```bash
ls -lh db/nexus.sqlite
```

You should see a file with a reasonable size (typically 10-50MB for thousands of items).

### 2. Query Video Count

```bash
sqlite3 db/nexus.sqlite "SELECT COUNT(*) FROM videos;"
```

### 3. Query Recent Videos

```bash
sqlite3 db/nexus.sqlite "SELECT title, published_iso FROM videos ORDER BY published_iso DESC LIMIT 5;"
```

### 4. Query Article Count

```bash
sqlite3 db/nexus.sqlite "SELECT COUNT(*) FROM articles;"
```

### 5. Test Ingestion

Run a test ingestion to ensure everything works:

```bash
./nexus ingest-youtube --since 1 --console
```

This should show recent videos and successfully write to the SQLite database.

## Switching Backends

After successful migration, switch to the SQLite backend:

### 1. Update Backend Configuration

Edit `config/writer.json`:

```json
{
  "backend": "sqlite",
  "db_path": null
}
```

- `"db_path": null` uses the default location: `db/nexus.sqlite`
- Or specify a custom path: `"db_path": "/custom/path/to/nexus.db"`

### 2. Test New Backend

```bash
# Test YouTube ingestion
./nexus ingest-youtube --since 24 --console

# Test HackerNews ingestion
./nexus ingest-hackernews --min-score 100 --since 24 --console
```

You should see successful ingestion without needing `NOTION_TOKEN`.

### 3. Remove Notion Token (Optional)

Once you're confident with SQLite, you can remove the Notion token from your environment:

```bash
# Remove from current session
unset NOTION_TOKEN

# Remove from .env file (if using)
# Edit .env and remove or comment out the NOTION_TOKEN line
```

## Rollback

If you need to switch back to Notion for any reason:

### 1. Restore Backend Configuration

Edit `config/writer.json`:

```json
{
  "backend": "notion"
}
```

### 2. Ensure Notion Token is Set

```bash
export NOTION_TOKEN="secret_..."
```

### 3. Verify Notion Databases

```bash
# The bootstrap command will validate your existing databases
./nexus notion
```

### 4. Resume Ingestion

```bash
./nexus ingest-youtube --since 24 --console
```

Your Notion databases still contain all the data from before migration. Nothing was deleted.

## Troubleshooting

### Error: NOTION_TOKEN not set

**Problem**: Migration requires read access to Notion.

**Solution**:
```bash
export NOTION_TOKEN="secret_..."
./nexus migrate
```

### Error: Notion database IDs not found

**Problem**: `config/notion.json` is missing database IDs.

**Solution**:
```bash
./nexus notion --parent-page-id <YOUR_PAGE_ID>
./nexus migrate
```

### Error: Database is locked

**Problem**: Another process is accessing the SQLite database.

**Solution**:
- Close any other Nexus processes
- Close any database browser tools (DB Browser for SQLite, etc.)
- The migration will automatically retry 3 times with exponential backoff
- If issue persists, restart and try again:
  ```bash
  ./nexus migrate
  ```

### Error: Failed to export videos/articles

**Problem**: Notion API request failed (rate limit, timeout, network issue).

**Solution**:
- Wait a few minutes and retry: `./nexus migrate`
- Check your internet connection
- Verify your Notion token is valid: `echo $NOTION_TOKEN`
- Check Notion's status page: https://status.notion.so/

### Migration is Very Slow

**Problem**: Large datasets can take time to export from Notion.

**Solution**:
- Be patient. Notion's API has rate limits.
- Typical rates: 200-500 items per minute
- For 10,000 items, expect 20-50 minutes
- Let it run in the background
- The migration is idempotent - if interrupted, just run it again

### Verification Shows Mismatched Counts

**Problem**: SQLite has different counts than expected.

**Possible Causes**:
1. **Notion pagination issue**: Retry migration
2. **Existing SQLite data**: Migration preserves existing data (upsert)
3. **Incomplete Notion data**: Some items may lack required fields (URL, title)

**Solution**:
```bash
# Check what was actually exported
sqlite3 db/nexus.sqlite "SELECT COUNT(*) FROM videos WHERE source = 'YouTube';"
sqlite3 db/nexus.sqlite "SELECT COUNT(*) FROM articles;"

# If needed, clear SQLite and re-migrate
rm db/nexus.sqlite
./nexus migrate
```

### Error: Permission Denied

**Problem**: Cannot write to `db/nexus.sqlite` or the `db/` directory.

**Solution**:
```bash
# Ensure directory exists
mkdir -p db

# Fix permissions
chmod 755 db
chmod 644 db/nexus.sqlite  # if file exists
```

## FAQ

### Q: Will my Notion data be deleted?

**A**: No. The migration only **reads** from Notion. Your Notion databases remain completely unchanged.

### Q: Can I run the migration multiple times?

**A**: Yes! The migration is idempotent. It uses upsert logic (insert or update), so running it multiple times is safe. This is useful if:
- Migration was interrupted
- You added new data to Notion after migration
- You want to keep SQLite and Notion in sync

### Q: What happens to new data ingested after migration?

**A**: After switching to SQLite backend, all new ingestion goes to SQLite. Your Notion databases won't receive new data unless you switch back to the Notion backend.

### Q: Can I use both backends simultaneously?

**A**: No. The backend is configured in `config/writer.json` and applies to all ingestion commands. However, you can:
1. Run migration to sync Notion → SQLite
2. Switch to SQLite for daily ingestion
3. Periodically sync by running migration again

### Q: How do I query my SQLite data?

**A**: Several options:

**Command Line**:
```bash
sqlite3 db/nexus.sqlite

# Interactive SQL
SELECT title, published_iso FROM videos LIMIT 10;
```

**Database Browser**:
- Download: [DB Browser for SQLite](https://sqlitebrowser.org/)
- Open `db/nexus.sqlite`

**Python**:
```python
import sqlite3
conn = sqlite3.connect('db/nexus.sqlite')
cursor = conn.cursor()
cursor.execute('SELECT * FROM videos ORDER BY published_iso DESC LIMIT 10')
for row in cursor.fetchall():
    print(row)
```

**Web UI**:
- Coming soon! A built-in web UI for browsing SQLite data.

### Q: What if I want to keep using Notion?

**A**: That's perfectly fine! The Notion backend is still fully supported. Simply keep:
```json
{
  "backend": "notion"
}
```

You don't need to migrate. Both backends are first-class citizens.

### Q: How much disk space will the SQLite database use?

**A**: Approximate sizes:
- **Videos** (no full text): ~500 bytes per item
- **Articles** (with full text): ~2-5 KB per item
- **Logs**: ~200 bytes per entry

Example: 5,000 videos + 2,000 articles + 10,000 logs = ~15-25 MB

### Q: Can I move my SQLite database to another computer?

**A**: Yes! Simply copy the `db/nexus.sqlite` file:

```bash
# On source computer
cp db/nexus.sqlite ~/Dropbox/nexus-backup.sqlite

# On destination computer
mkdir -p db
cp ~/Dropbox/nexus-backup.sqlite db/nexus.sqlite
```

Then use it on the new machine. This makes Nexus completely portable.

### Q: What about the queue database (db/queue.sqlite)?

**A**: The `queue.sqlite` database tracks ingestion state and is separate from your content database:
- It stores content hashes for deduplication
- It's automatically created and maintained
- It works with both Notion and SQLite backends
- Migration doesn't affect it

### Q: How do I export my data to another format?

**A**: SQLite makes this easy:

**CSV Export**:
```bash
sqlite3 -header -csv db/nexus.sqlite "SELECT * FROM videos;" > videos.csv
sqlite3 -header -csv db/nexus.sqlite "SELECT * FROM articles;" > articles.csv
```

**JSON Export** (requires jq):
```bash
sqlite3 db/nexus.sqlite "SELECT json_object(
  'title', title,
  'url', url,
  'summary', summary
) FROM videos;" | jq -s '.'
```

### Q: Can I run migration in the background?

**A**: Yes, but use `--yes` to skip the confirmation prompt:

```bash
nohup ./nexus migrate --yes > migration.log 2>&1 &

# Monitor progress
tail -f migration.log
```

### Q: What if I encounter an error not listed here?

**A**: Please:
1. Check the error message carefully
2. Review your configuration files (`config/writer.json`, `config/notion.json`)
3. Try running migration again (it's safe and idempotent)
4. Check the project's issue tracker or documentation
5. Verify your Notion token has proper permissions

---

## Need Help?

If you encounter issues not covered in this guide:

1. Check the main README troubleshooting section
2. Verify your configuration files are valid JSON
3. Run migration with `--yes` flag to bypass prompts for automation
4. Check Notion's status: https://status.notion.so/
5. Review the error message and logs carefully

The migration is designed to be safe and reliable. Most issues can be resolved by simply retrying the migration command.
