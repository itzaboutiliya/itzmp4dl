# iTZMP4DL

Telegram downloader with MP4 resolution selection, MP3 at 128/192/320 kbps,
SQLite authorization, and owner access management. Uses yt-dlp and FFmpeg.

Regular messages are ignored unless they contain an HTTP(S) website link.
Telegram domains and their subdomains are ignored. Hidden text links and photo
captions are supported. If a message has multiple website links, only the first
is processed. Commands such as `/start` and `/unlock` respond explicitly.

## Run locally

Requires Python 3.11+, FFmpeg/ffprobe on PATH, and Node.js 20+ for extractors
requiring JavaScript. Docker installs these for hosting.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env locally with your secrets, then:
.\.venv\Scripts\python.exe bot.py
```

Create a bot with @BotFather or reuse your existing bot. If its old token may
still be running elsewhere, regenerate the token in BotFather before deployment.
Set BOT_TOKEN, a random ACCESS_KEY of at least 12 characters (prefer 24+), and
OWNER_IDS (comma-separated numeric Telegram user IDs). `/id` displays IDs before
activation. Do not commit `.env`. Owner IDs have automatic access.

## Railway deployment

1. Upload this folder as a GitHub repository, or set Railway's service root
   directory to `/itzmp4dl` if uploading the enclosing repository.
2. Create a Railway service from that repository. It builds the Dockerfile.
3. Add BOT_TOKEN, ACCESS_KEY, OWNER_IDS, DATA_DIR=/data as service variables.
4. **Attach a persistent volume mounted at `/data`.** SQLite approvals will be
   lost on replacement deployments without persistent storage. Confirm your
   Railway plan supports a volume before relying on remembered access.
5. Use exactly one replica. No public domain or inbound port is needed; this
   bot uses long polling. Disable sleeping/serverless mode for polling.
6. Deploy, open Telegram, run `/start`, then send a website link.

Railway free credits may not cover continuous operation or downloads. Track
usage in its dashboard. There is no guarantee of indefinitely free hosting.

## Access and group setup

- Private: `/unlock YOUR_KEY` authorizes that user's numeric Telegram ID.
- Group: an administrator runs `/unlock YOUR_KEY`; all members can then use the
  bot **in that group**. Private access remains separate.
- The bot attempts to delete the key message. Give it Delete Messages permission
  in groups. A key sent in a group may be visible before deletion; use owner
  `/grant GROUP_ID` privately if you do not want to share the key with members.
- Make the bot a group administrator for reliable admin checks and link delivery.
  Alternatively disable privacy mode using BotFather `/setprivacy` and re-add
  the bot. `/download URL` works when normal group links are not delivered.
- `/lock`: remove this user's/private chat access, or this group's access when
  invoked by a group administrator.
- Owner commands, **in private only**: `/authorized`, `/grant ID`, `/revoke ID`.
- Change ACCESS_KEY in Railway variables and redeploy to rotate it. Existing
  approvals remain. Use `/revoke` to remove them.
- Five wrong key attempts per user trigger a 15-minute cooldown. This cooldown
  is in memory and resets on restart. Grants persist in SQLite.

## Limits and behavior

Accepts links from any public website, with no fixed site allowlist; actual
download support depends on yt-dlp and the website. Includes direct MP4 links.
Login-only, blocked and DRM-protected media may fail. No cookies are bundled.
Only download material you are entitled to download.

MP4 resolutions are discovered per video; selection means **up to** that height.
Best available is offered when resolution metadata is missing. MP3 bitrate is
an encoding setting and cannot restore quality missing from the source.

One active inspection/download/upload at a time; additional requests get a busy
reply. Menus expire after 15 minutes and only their requester can operate them.
Restarting loses menus, not saved access. Live streams and playlists are rejected.
Default duration limit: 30 minutes, configurable with MAX_DURATION in seconds.
Download timeout: 600 seconds, configurable with JOB_TIMEOUT. Output limit: 49 MB
to stay under Telegram's standard cloud Bot API 50 MB upload limit. Intermediate
disk usage is checked every half second against 180 MB; it is not an OS disk quota.
Large results fail with advice to choose lower quality. Temporary files are
cleaned after success or failure; Docker process groups stop download descendants
on timeout. Windows local runs do not provide the same descendant cleanup.

Initial submitted URLs are checked against private/local IPs. Extractor requests,
redirects and DNS rebinding are not sandboxed by this application. Keep the key
restricted to trusted people; stronger network isolation is needed for an open
public service. Secrets and downloader error output are omitted from application
logs. The bot never stores the access key in its authorization database.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Tests cover ignored text/Telegram links, mixed URLs, persistent authorization,
private-address checks, and group admin activation. Real Telegram delivery needs
your token and live testing. FFmpeg and Docker hosting must also be verified on
the deployed service. Update yt-dlp and rebuild periodically as websites change.
