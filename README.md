# Telegram Channel Copier — Render Control Bot

A Render-ready Telegram bot for copying **existing** messages from one channel to another **without a forward/source label**.

All source channel IDs, target channel IDs, message-ID ranges, speed settings, progress destination, pause/resume state, and status are controlled from private bot commands. You do not edit source code to change a copy job.

> [!IMPORTANT]
> This project uses the Telegram **Bot API** only. It does **not** need `API_ID`, `API_HASH`, phone numbers, SMS codes, a user session, or two-factor passwords.
>
> A bot cannot list old channel history. The copier instead tries every source message ID inside the range you set. Deleted, service, protected, text-only, unsupported, or non-copyable posts are logged as **skipped**.

## What it does

- Copies old files, videos, documents, photos, audio, and their captions as new messages.
- No source attribution or “Forwarded from” label.
- Uses `copyMessages` in batches, with individual fallback for mixed/deleted ranges.
- Saves channel settings and progress in SQLite.
- Supports pause, restart-safe resume, speed/ETA, and a single editable Telegram progress post.
- Long-polls Telegram; no public webhook URL or port is required.
- Restricts commands to one private owner account.

## Before deploying

1. Create a Telegram bot with **@BotFather** and keep its token private.
2. Add the bot as an **administrator** in both channels:
   - **Source channel:** the bot must be able to access posts.
   - **Target channel:** grant **Post Messages**.
3. Make sure copying is permitted for the source posts. Telegram-protected posts cannot be copied.

## Deploy to Render

This repo includes `render.yaml` for a Render **Background Worker** with a 1 GB persistent disk at `/var/data`.

1. Upload this project to a new GitHub repository.
2. In Render: **New → Blueprint** and select the GitHub repository.
3. Render reads `render.yaml`. Enter only `BOT_TOKEN` when prompted.
4. Deploy.
5. Open your bot in Telegram, press **Start**, then send:

```text
/claim
```

The first account that sends `/claim` becomes the only controller. For stricter preconfigured ownership, add your numeric Telegram user ID as the Render secret `OWNER_ID` before deploying. You can get it by sending `/id` to this bot after its first deployment, then add `OWNER_ID` and redeploy.

### Render plan note

Render does not provide a free background-worker plan, and persistent disks are paid. This project intentionally uses a background worker because it must stay connected to Telegram and preserve copy progress. The persistent disk stores the SQLite database and log under `/var/data` across redeploys/restarts.

## Bot commands

Start by sending `/help` to your bot privately.

### Configure source, target, and message IDs

```text
/setsource -1003033186334
/settarget -1004393739586
/setrange 1 2123
```

You may paste a private source message link into `/setsource` instead:

```text
/setsource https://t.me/c/3033186334/181
```

It automatically becomes `-1003033186334`.

To set range endpoints separately:

```text
/setstart 1
/setend 2123
```

You can paste a message link wherever an ID is accepted; the bot reads the final message number.

### Test one real file first

```text
/test 181
```

A successful test copies the selected file into the target channel. If the test fails, verify the source/target IDs, source access, target Post Messages permission, and whether that post is protected.

### Start, pause, resume

```text
/copy
/status
/pause
/resume
```

`/pause` saves the next source message ID. `/resume` continues from that exact ID. `/restart` deliberately starts the configured range over from its beginning.

### Performance and progress post

```text
/setbatch 25
/setdelay 0.6
/setprogress owner
```

Progress choices:

```text
/setprogress owner      # edit one private message in your bot chat
/setprogress target     # edit one status message in the target channel
/setprogress -100...    # edit one message in another chat/channel
```

The progress view reports scanned source message IDs, copied/skipped totals, speed, and ETA. It is a message-ID scan, not a pre-counted list of files, because the Bot API cannot enumerate old channel history.

## Local run (optional)

```bash
cp .env.example .env
nano .env
./local.sh
```

The local data directory defaults to `./data`. On Render it is `/var/data`.

## Files

```text
main.py             Render entry point
app/api.py          Telegram Bot API client
app/store.py        Persistent SQLite settings + job state
app/copier.py       Copy engine, retries, progress and resume
app/bot.py          Owner-only private bot commands
render.yaml         Render Background Worker blueprint
```

## Safety / Telegram limits

- The bot waits automatically for Telegram flood limits and retries temporary network failures.
- The same Bot API token must run in only one active instance. Two instances produce Telegram `getUpdates` conflicts.
- A protected source channel/post cannot be copied by a bot.
- Do not expose `BOT_TOKEN`, `OWNER_ID`, or the persistent database directory.
