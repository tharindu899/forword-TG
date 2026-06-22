---
title: Telegram Channel Copier
emoji: 📦
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:1D4ED8,50:7C3AED,100:0EA5E9&height=220&section=header&text=Telegram%20Channel%20Copier&fontSize=40&fontColor=ffffff&animation=fadeIn&fontAlignY=38&desc=Private%20MTProto%20media%20migration%20with%20one%20live%20control%20panel&descAlignY=58&descSize=17" alt="Telegram Channel Copier banner" />
</p>

<p align="center">
  <a href="#hugging-face-space-deploy"><img src="https://img.shields.io/badge/Hugging%20Face-Docker%20Space-FF9D00?logo=huggingface&logoColor=white" alt="Hugging Face Docker Space" /></a>
  <a href="#termux-local-setup"><img src="https://img.shields.io/badge/Termux-Local%20Run-000000?logo=termux&logoColor=white" alt="Termux local run" /></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/Pyrogram-MTProto-2CA5E0?logo=telegram&logoColor=white" alt="Pyrogram MTProto" />
  <img src="https://img.shields.io/badge/Panel-Owner%20Only-16A34A" alt="Owner only panel" />
  <img src="https://img.shields.io/badge/Logs-SLST%20%28Asia%2FColombo%29-7C3AED" alt="Sri Lanka time logs" />
</p>

<p align="center">
  <b>Copy existing Telegram media from one channel to another through a single private control panel.</b><br />
  Built for channel owners and administrators who need a clean migration workflow, live progress, safe pause/resume, and no visible original-channel attribution where Telegram allows it.
</p>

> [!IMPORTANT]
> **Privacy first:** this repository intentionally contains **no real bot token, API ID, API hash, owner ID, phone number, channel ID, post link, or session file.** Keep all private values only in Hugging Face Secrets or your local `.env` file.

## ✨ Highlights

> [!NOTE]
> **Optional delete range behavior:** choose **🗑 Use Copy Range** to delete the currently saved copy range, or choose **🎯 Custom Range** to override it for one delete action. A bounded final range and confirmation are always required.

- 📦 Copies old channel **media posts** from a chosen source range into a target channel.
- 🕶️ Uses MTProto forwarding with original-author attribution removed where Telegram permits it.
- 🧭 One editable private-message card for setup, progress, pause, errors, and completion.
- 📊 Accurate progress bar: `■` complete, `□` remaining, and `▤ ▥ ▦ ▧ ▨ ▩` for the partial cell.
- ⏸️ Pause safely and resume from the saved **Next ID**.
- ⚡ Safe, Balanced, and Fast speed profiles.
- 🔒 Owner-only controls: other users cannot run migrations or edit setup.
- 🕒 Application logs use **Sri Lanka Standard Time** (`SLST`, `Asia/Colombo`).
- 🧩 Supports public usernames, private channel IDs, and Telegram post links.
- 🗑️ Deletes messages from one selected channel with an optional custom range, final confirmation, and safe default copy range.
- ☁️ Runs on a Hugging Face Docker Space or locally on Android Termux.

---

## 🧭 How it works

1. The bot runs using **Pyrogram + MTProto** with your bot token and Telegram API credentials.
2. You open the bot’s private chat and send `/start`.
3. One control card appears. Use inline buttons to set or change source, target, range, test file, and speed.
4. Use **🗑 Source**, **🗑 Target**, or **🗑 Range** when a migration is done or you want to reuse the bot for another channel. Each clear action resets saved copy counters safely.
5. The bot checks one media post with **🧪 Test**.
6. Tap **▶️ Start**. The same card updates while copying.
6. Telegram may temporarily throttle forwarding. The app waits automatically and continues.
7. Use **🗑 Delete Messages** only when needed: choose one channel, use the saved copy range or optionally set a custom range, then confirm.
8. When the range finishes, the card changes to **✅ COMPLETE**.

### Panel preview

```text
▤ CHANNEL COPIER
├ 🟢 RUNNING  •  35.4%
├ ■■■■▥□□□□□□□  752 / 2,123
├ ✅ 710 copied  •  ⏭ 41 skipped
├ 📥 Next 752  •  ⚡ 3.42/s
├ ⏳ 6m 18s  •  🕒 3m 44s
├ 🎯 <START_ID> → <END_ID>  •  ⚡ Balanced
├ 📥 <SOURCE_CHANNEL>
└ 📤 <TARGET_CHANNEL>
```

### 🧹 Change or clear saved setup

Open **⚙️ Setup** from the panel. All setup actions stay inside the same editable message:

| Button | What it does |
|---|---|
| 📥 Source | Set or replace the old/source channel |
| 📤 Target | Set or replace the new/target channel |
| 🎯 Range | Set or replace the start and end message IDs |
| 🗑 Delete Messages | Choose one channel and delete a confirmed, bounded message range |
| 🗑 Source | Clear only the saved source channel |
| 🗑 Target | Clear only the saved target channel |
| 🗑 Range | Clear only the saved message range back to `1 → 0` |

> [!TIP]
> Clear buttons are available only while no copy task is running. Pause the task first, then change or clear its setup.

### 🗑 Delete messages safely

The delete tool works on **one selected channel at a time**. It uses the same one private control card and requires final confirmation.

1. Open **⚙️ Setup** → **🗑 Delete Messages**.
2. Choose **📥 Source** or **📤 Target**.
3. Choose one option:
   - **🗑 Use Copy Range** — uses the already-saved main copy range; no extra delete range is required.
   - **🎯 Custom Range** — optional override for this deletion only. Send `<START_MESSAGE_ID> <END_MESSAGE_ID>`.
4. Review the selected channel, final range, and message count.
5. Press **🗑 CONFIRM DELETE**. The same card becomes the delete-progress card.

> [!IMPORTANT]
> The custom delete range is optional, but deletion is always bounded. When you skip Custom Range, the bot uses the saved **Copy Range**. It never deletes an entire channel without a final message ID.

> [!CAUTION]
> Deleted messages cannot be restored. The bot needs **Delete Messages** administrator permission in the selected channel. **✕ Cancel** is available on every temporary delete screen.

---

## ✅ Requirements

### Telegram permissions

Before starting, add the bot to both channels:

| Channel | Required access |
|---|---|
| 📥 Source channel | The bot must be an **Administrator** and able to access the posts you want to copy. |
| 📤 Target channel | The bot must be an **Administrator** with permission to **post messages**. |
| 🗑 Selected delete channel | The bot must be an **Administrator** with permission to **Delete Messages**. |
| 👤 Owner private chat | Start the bot once, so it can create and update the private control card. |

### Telegram developer credentials

This project uses MTProto, so it needs all four settings:

| Secret | Purpose |
|---|---|
| `BOT_TOKEN` | Bot token created with BotFather. |
| `OWNER_ID` | Your numeric Telegram user ID. Only this account controls the panel. |
| `API_ID` | Telegram developer application ID from `my.telegram.org/apps`. |
| `API_HASH` | Telegram developer application hash from `my.telegram.org/apps`. |

> [!CAUTION]
> Never paste any secret value into GitHub, Hugging Face repository files, screenshots, logs, Telegram groups, or support chats. Use placeholders such as `<BOT_TOKEN>` in examples only.

---

# ☁️ Hugging Face Space deploy

## 1. Create the Space

1. Open Hugging Face and create a new **Space**.
2. Choose **Docker** as the SDK.
3. Choose a visibility level suitable for your project. A private Space is recommended when the repository may contain operational settings.
4. Create the Space.

The README front matter at the top of this file already tells Hugging Face to use Docker and port `7860`.

## 2. Upload or push the project

### Option A — Upload files

Extract this project and upload the contents to the Space repository. Keep the folder structure unchanged:

```text
app/
Dockerfile
requirements.txt
space_main.py
README.md
.env.example
.gitignore
```

### Option B — Push from GitHub or Termux

```bash
git clone https://huggingface.co/spaces/<HF_USERNAME>/<SPACE_NAME>.git
cd <SPACE_NAME>
# Copy this project’s files into this folder
git add -A
git commit -m "Deploy Telegram Channel Copier"
git push
```

## 3. Add Space Secrets

Open **Space Settings → Variables and Secrets** and create these as **Secrets**:

```env
BOT_TOKEN=<YOUR_BOT_TOKEN>
OWNER_ID=<YOUR_NUMERIC_TELEGRAM_USER_ID>
API_ID=<YOUR_TELEGRAM_API_ID>
API_HASH=<YOUR_TELEGRAM_API_HASH>
```

Optional runtime values can be added as Variables or Secrets:

```env
SESSION_NAME=channel_copier_mtproto_bot
DATA_DIR=/app/data
AUTO_RESUME=true
PYROGRAM_IPV6=false
LOG_LEVEL=INFO
```

## 4. Confirm startup

A healthy Space log includes lines similar to:

```text
Connected via MTProto as @your_bot_username
Registered compact command menu (4 commands)
Hugging Face Space health endpoint listening on port 7860
```

Then open the bot private chat and send:

```text
/start
```

> [!TIP]
> If a hosted environment restarts and does not retain local files, the saved range/progress database may be reset. Before changing hosting or restarting, note the **Next ID** from the panel. Set the next range from that ID and continue.

---

# 📱 Termux local setup

Run the same project directly on Android through Termux.

## 1. Install packages

```bash
pkg update -y && pkg upgrade -y
pkg install python python-pip git tmux -y
```

> [!NOTE]
> Do **not** run `python -m pip install --upgrade pip` in Termux. Termux manages its own `pip` package.

## 2. Get the project

### From GitHub

```bash
git clone https://github.com/<GITHUB_USERNAME>/<REPOSITORY_NAME>.git channel-copier
cd channel-copier
```

### From a Hugging Face Space repository

```bash
git clone https://huggingface.co/spaces/<HF_USERNAME>/<SPACE_NAME>.git channel-copier
cd channel-copier
```

## 3. Install Python libraries

```bash
python -m pip install --no-cache-dir -r requirements.txt
```

## 4. Create local settings

```bash
cp .env.example .env
nano .env
```

Use placeholders replaced only on your own device:

```env
BOT_TOKEN=<YOUR_BOT_TOKEN>
OWNER_ID=<YOUR_NUMERIC_TELEGRAM_USER_ID>
API_ID=<YOUR_TELEGRAM_API_ID>
API_HASH=<YOUR_TELEGRAM_API_HASH>

SESSION_NAME=channel_copier_mtproto_bot
DATA_DIR=./data
AUTO_RESUME=true
PYROGRAM_IPV6=false
LOG_LEVEL=INFO
```

Save in Nano: **CTRL + O**, Enter, then **CTRL + X**.

## 5. Start the bot

```bash
termux-wake-lock
python space_main.py
```

Open the bot PM and send `/start`.

## 6. Keep it running in tmux

```bash
tmux new -s channel-copier
python space_main.py
```

Detach without stopping the app: **CTRL + B**, then **D**.

Return later:

```bash
tmux attach -t channel-copier
```

Stop the current copy safely from the bot panel using **⏸ Pause**. To stop the local process completely, open the tmux session and press **CTRL + C**.

---

# 🎛 Control panel guide

The bot intentionally has only four visible slash commands. Everything else is handled through inline buttons.

## Visible commands

| Command | What it does |
|---|---|
| `/start` | Opens or refreshes the single private control card. |
| `/copy` | Starts a new configured job or resumes a paused one. |
| `/pause` | Requests a safe pause after the current Telegram request finishes. |
| `/status` | Refreshes the current control card. |

## Recovery commands

These are not shown in the main command menu:

| Command | When to use it |
|---|---|
| `/syncmenu` | Force a command-menu refresh after a redeploy. Close and reopen the bot PM afterward. |
| `/claim` | Only for initial recovery when `OWNER_ID` was intentionally left empty. After claiming, set a fixed `OWNER_ID` secret and restart the app. |

## Inline buttons

| Button | Action |
|---|---|
| `⚙️ Setup` | Opens source, target, range, test, and speed settings. |
| `📥 Source` | Set the old/source channel. |
| `📤 Target` | Set the new/target channel. |
| `🎯 Range` | Set the first and last message IDs to process. |
| `🧪 Test` | Copy one known media post first. Use this before a large migration. |
| `⚡ Speed` | Choose Safe, Balanced, or Fast. |
| `▶️ Start / Resume` | Begin the configured range or continue a paused run. |
| `⏸ Pause` | Stop safely after the active request. |
| `🔄 Refresh` | Redraw the same status card. |

---

# ✍️ Accepted input formats

## Source or target channel

You can submit any one of these:

```text
@channel_username
https://t.me/channel_username
https://t.me/c/<PRIVATE_CHANNEL_PART>/<POST_ID>
-100<PRIVATE_CHANNEL_ID>
```

For a private channel post link, the app derives the channel reference automatically.

## Range

Send two message IDs separated by a space:

```text
<START_MESSAGE_ID> <END_MESSAGE_ID>
```

Example workflow:

1. Copy a link from the oldest media post you want.
2. Copy a link from the newest media post you want.
3. Take the final message number from each link.
4. Use the older number as Start and newer number as End.

## Test file

Send either a single post ID or a post link:

```text
<FILE_MESSAGE_ID>
https://t.me/c/<PRIVATE_CHANNEL_PART>/<FILE_MESSAGE_ID>
```

A successful test means the bot can access the source post and can post into the target channel.

---

# 🚀 Recommended migration workflow

1. Add the bot as admin in both channels.
2. Open bot PM → `/start`.
3. Tap **⚙️ Setup**.
4. Set **📥 Source**.
5. Set **📤 Target**.
6. Set **🎯 Range**.
7. Tap **🧪 Test** and enter one known media post ID.
8. Select **⚡ Balanced** speed for the first run.
9. Tap **▶️ Start**.
10. Watch the one live panel. Do not tap Start repeatedly.
11. When it shows **✅ COMPLETE**, compare copied media with the source range.

---

# 📊 Progress, pause, and resume

## Progress bar meaning

```text
■■■■▦□□□□□□□
```

| Symbol | Meaning |
|---|---|
| `■` | One fully completed bar cell. |
| `□` | One remaining bar cell. |
| `▤ ▥ ▦ ▧ ▨ ▩` | One partial cell showing the fractional amount between full and empty. |

## Why copied + skipped equals total IDs

The copier works through **message IDs**, not a pre-built media list. A channel range can contain deleted IDs, service messages, plain text, albums that behave differently, unavailable media, protected posts, or posts Telegram will not permit the bot to copy.

So this is normal:

```text
Processed IDs = copied posts + skipped posts
```

A high skipped count does not automatically mean the migration failed.

## Pause safely

Tap **⏸ Pause** once. The card changes to **PAUSING**, then **PAUSED** when the current Telegram action finishes.

## Resume

Tap **▶️ Resume**. The app continues from the saved **Next ID** rather than beginning the range again.

## Resume after a restart

When local data is preserved, `AUTO_RESUME=true` restores an interrupted job as a paused state. Open the panel and tap Resume.

When the host lost local data, set a new range beginning at the **Next ID** you noted before the restart. Always run a quick test before resuming a large range.

---

# ⚡ Speed profiles

| Profile | Batch size | Delay | Best for |
|---|---:|---:|---|
| 🐢 Safe | 10 | 0.90s | Unstable networks or frequent Telegram limits. |
| ⚖️ Balanced | 25 | 0.60s | Recommended starting point. |
| 🚀 Fast | 50 | 0.40s | Small ranges or stable conditions; may trigger more flood waits. |

Telegram can return a **FloodWait** during heavy forwarding. The app waits the required time automatically; it is not a failure.

---

# 🔐 Security checklist

- [ ] Keep `BOT_TOKEN`, `API_ID`, `API_HASH`, and `OWNER_ID` only in Space Secrets or `.env`.
- [ ] Keep `.env`, `data/`, `*.session`, and `*.session-journal` out of git.
- [ ] Keep the repository private when it contains operational material.
- [ ] Do not publish logs that contain private IDs, message links, or tokens.
- [ ] Do not share the bot’s private control panel with other users.
- [ ] Regenerate a token or API credential immediately if it was pasted publicly.

The included `.gitignore` already excludes local secrets, sessions, bytecode, and runtime data.

---

# 🧩 Configuration reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | BotFather token used to log in as the bot. |
| `OWNER_ID` | ✅ recommended | `0` | Numeric user ID allowed to control the bot. |
| `API_ID` | ✅ | — | Telegram API application ID for Pyrogram MTProto. |
| `API_HASH` | ✅ | — | Telegram API application hash for Pyrogram MTProto. |
| `SESSION_NAME` | Optional | `channel_copier_mtproto_bot` | Local Pyrogram session file name. |
| `DATA_DIR` | Optional | `./data` | Folder for SQLite state, session, and logs. |
| `AUTO_RESUME` | Optional | `true` | Marks interrupted jobs as resumable on the next startup. |
| `PYROGRAM_IPV6` | Optional | `false` | Enable only when your host has working IPv6 connectivity. |
| `LOG_LEVEL` | Optional | `INFO` | Logging level, such as `INFO` or `DEBUG`. |

---

# 🗂️ Full project file structure

> [!TIP]
> Upload the **project files** below to GitHub or your Hugging Face Docker Space. Keep the **local-only runtime files** section private — those files are created after the app starts and must never be committed.

```text
📦 telegram-channel-copier/
├── 📁 app/                                      # Main application package
│   ├── 🧩 __init__.py                           # Marks app as a Python package
│   ├── 🔌 api.py                                # MTProto bridge, forwarding and copy helpers
│   ├── 🎛️ bot.py                                # Owner PM panel, buttons, commands and replies
│   ├── ⚙️ config.py                              # Reads safe environment configuration
│   ├── 📦 copier.py                             # Copy worker, rate waits, progress and resume
│   ├── 🛡️ pyrogram_compat.py                    # New private-channel ID compatibility patch
│   └── 🗃️ store.py                              # SQLite settings, saved range and job state
│
├── 🐳 Dockerfile                                # Hugging Face Docker image and SLST timezone
├── 📚 requirements.txt                          # Python libraries: Pyrogram + runtime packages
├── 🚀 space_main.py                             # App entry point + Hugging Face health endpoint
├── 🔐 .env.example                              # Safe placeholder template — no real values
├── 🙈 .gitignore                                # Prevents secrets, sessions, logs and data uploads
├── 📖 README.md                                 # Full GitHub, Hugging Face and Termux guide
└── 📝 CHANGELOG.md                              # Version notes and UI / behavior updates
```

## 🔒 Local-only runtime files — never upload

These files are generated only after the bot runs. They are intentionally excluded by `.gitignore`.

```text
📁 data/                                         # Created from DATA_DIR
├── 🗃️ channel_copier.sqlite3                    # Setup, progress, saved next ID and panel state
├── 📜 copier.log                                # Copy activity log in SLST / Asia-Colombo time
├── 🔑 channel_copier_mtproto_bot.session        # Pyrogram bot session — private
└── 🔐 channel_copier_mtproto_bot.session-journal # Session journal — private

📁 __pycache__/                                  # Python cache — safe to delete, never commit
```

### 📤 Files you should upload

```text
✅ app/
✅ Dockerfile
✅ requirements.txt
✅ space_main.py
✅ .env.example
✅ .gitignore
✅ README.md
✅ CHANGELOG.md
```

### 🚫 Files you must not upload

```text
❌ .env
❌ data/
❌ *.session
❌ *.session-journal
❌ copier.log
❌ __pycache__/
❌ Any screenshot, log, or text file containing real tokens, IDs, links or secrets
```

---

# 🕒 Sri Lanka time logs

The app writes console and `copier.log` timestamps in `SLST` (`Asia/Colombo`, UTC+05:30).

Example:

```text
2026-06-22 21:40:20,095 SLST | INFO  | app.copier | Copying configured source IDs.
```

On Termux, the log file is stored inside your `DATA_DIR`. On Hugging Face, it is created inside the Space container’s configured data directory.

---

# 🛠 Troubleshooting

## `PEER_ID_INVALID` or “peer not known yet”

- Confirm the channel value is correct.
- Add the bot as an admin in the source and target channels.
- Restart the app after adding the bot.
- Prefer a public `@username` or a copied Telegram post link when available.
- Test one known media post again.

## `not enough rights`, `forbidden`, or `bot was kicked`

The bot lacks channel access. Add it back as an administrator and make sure target posting permission is enabled.

## `FloodWait` / “Waiting for N seconds”

Normal Telegram throttling. The app is automatically waiting. Do not restart it or tap Start again.

## `MESSAGE_NOT_MODIFIED`

Harmless. It means the app attempted to update the live panel with exactly the same content.

## Test passes but some posts are skipped

Expected for deleted IDs, non-media posts, protected/unavailable media, or unsupported Telegram content. The app logs totals so you can compare the range later.

## The command menu does not show

1. Send `/syncmenu` manually in bot PM.
2. Wait for the Space/Termux logs to confirm command registration.
3. Close and reopen the Telegram chat with the bot.
4. You can still type `/start`, `/copy`, `/pause`, and `/status` manually.

## The bot started but the panel does not appear

- Check that `OWNER_ID` matches your own numeric Telegram user ID.
- Send `/start` from that same Telegram account.
- Check the Space/Termux logs for startup errors.

## The app restarted during a copy

Open the panel. If the saved state remains, the job appears paused and can be resumed. If state was lost, begin a new range from the last recorded Next ID.

---

# 🔄 Updating the project

## GitHub workflow

```bash
git add -A
git status
git commit -m "Describe your update"
git push
```

Before committing, confirm `.env`, session files, and `data/` do not appear in `git status`.

## Hugging Face workflow

Push to the Space repository or upload the changed files. Hugging Face rebuilds the Docker Space from the repository files.

After a UI update, send:

```text
/syncmenu
```

Then reopen the bot PM to refresh the command list.

---

# 🤝 Responsible use

Use this tool only with channels and media you own or are authorized to administer. Respect Telegram rules, rights holders, privacy, and content-protection settings. Do not use it to bypass protected content or access controls.

---

<p align="center">
  <b>📦 Telegram Channel Copier</b><br />
  <sub>Private • owner-controlled • resumable • mobile-friendly</sub>
</p>
