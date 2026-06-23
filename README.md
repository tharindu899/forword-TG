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
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:1D4ED8,50:7C3AED,100:0EA5E9&height=220&section=header&text=Telegram%20Channel%20Copier&fontSize=40&fontColor=ffffff&animation=fadeIn&fontAlignY=38&desc=Multi-user%20private%20channel%20migration%20with%20separate%20task%20panels&descAlignY=58&descSize=17" alt="Telegram Channel Copier banner" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Mode-Multi--User-16A34A" alt="Multi User" />
  <img src="https://img.shields.io/badge/Hugging%20Face-Docker%20Space-FF9D00?logo=huggingface&logoColor=white" alt="Hugging Face Docker Space" />
  <img src="https://img.shields.io/badge/Termux-Ready-000000?logo=termux&logoColor=white" alt="Termux" />
  <img src="https://img.shields.io/badge/Pyrogram-MTProto-2CA5E0?logo=telegram&logoColor=white" alt="Pyrogram MTProto" />
  <img src="https://img.shields.io/badge/Logs-SLST-7C3AED" alt="Sri Lanka Time" />
  <a href="https://t.me/ChanRelayBot"><img src="https://img.shields.io/badge/Telegram-%40ChanRelayBot-2CA5E0?logo=telegram&logoColor=white" alt="Open @ChanRelayBot" /></a>
  <a href="https://github.com/tharindu899"><img src="https://img.shields.io/badge/GitHub-tharindu899-181717?logo=github&logoColor=white" alt="GitHub tharindu899" /></a>
</p>

# 📦 Telegram Channel Copier — Multi-User

<p align="center">
  <b>🤖 Bot username:</b> <a href="https://t.me/ChanRelayBot">@ChanRelayBot</a>
</p>

<p align="center">
  <img src="./assets/chan-relay-bot-logo.png" width="170" alt="@ChanRelayBot round logo" />
</p>

A private-chat Telegram bot for moving existing media from one channel to another without visible source attribution where Telegram permits it. Every user gets their **own setup**, **own task**, and **own one-message live panel**. Optional force-subscription can require users to join your update channel before they open their workspace.

> [!IMPORTANT]
> This repository contains no real channel IDs, token, API ID, API hash, phone number, owner ID, session file, or task database.
>
> `CHANNEL_WELCOME.md` is included at the repository root so it appears in your GitHub project under **tharindu899** after you push this ZIP.

## 🤖 Bot account

- **Telegram username:** [@ChanRelayBot](https://t.me/ChanRelayBot)
- Open the bot in a private chat and send `/start` to create your own panel.
- The bot profile icon is the round **Chan Relay** logo included with this release.

## 📢 Force subscription channel

Recommended community-channel identity:

- **Channel name:** `Tharindu Hub ✨`
- **Username:** `@TharinduHub` *(check availability in Telegram before creating it)*
- **Use it for:** updates, useful tools, projects, releases, and announcements.

Create the public channel, add **@ChanRelayBot** as an administrator, then set only this Hugging Face variable:

```env
FORCE_SUB_CHANNEL=@TharinduHub
```

That is enough. The bot automatically creates the join link from the username and fetches the channel’s visible Telegram name. Users will see a join card like:

```text
▤ CHAN RELAY
├ 📢 Join Tharindu Hub ✨ · @TharinduHub to unlock the bot.
├ 🔒 Your own channels and tasks stay private after access is verified.
└ ✅ Join the channel, then press Verify Access.
```

Leave `FORCE_SUB_CHANNEL` empty to disable the join requirement. The bot must remain an admin in the required channel so it can verify membership.

### 📣 General channel welcome post

A ready-to-post community welcome message is included as [`CHANNEL_WELCOME.md`](./CHANNEL_WELCOME.md). It includes your GitHub profile link and is not limited to this project:

```text
▤ THARINDU HUB
├ 👋 Welcome to our official community space.
├ ✨ New tools, projects, updates, releases, and useful ideas are shared here.
├ 💻 GitHub: https://github.com/tharindu899
├ 📌 Stay subscribed so you never miss an announcement.
└ 🚀 Thanks for being part of the journey.
```

## 👥 Multi-user behavior

- ✅ Anyone can open the bot in a private chat when `ALLOW_ALL_USERS=true`.
- 🔐 Each user has separate Source, Target, Range, task counts, pending input, delete confirmation, and private status-card ID.
- 🚫 Users cannot view or control another user's task through the bot UI.
- 🆕 `/start` creates a fresh welcome card for that user and makes it the only live card for future updates.
- 📊 Background progress edits only that user's newest private card. Old cards are never reused or updated.
- ⏸️ On a restart, each interrupted task becomes **Paused**. Only its own user can resume it.

> [!CAUTION]
> This is a powerful admin bot. Every user who can access the bot may use it only in channels where the bot itself has permissions. Do not leave the bot as an administrator in channels you do not want bot users to operate on. For public access, use a dedicated bot and separate channels.

## 🎛️ Commands

| Command | Action |
|---|---|
| `/start` | Send a fresh private welcome card and make it your live panel |
| `/help` | Show the compact guide for all commands |
| `/copy` | Start a new copy task using your saved setup |
| `/pause` | Safely pause your own active task |
| `/status` | Refresh your own latest panel |
| `/clean` | Opens inline buttons: Source, Target, or Range |
| `/delete` | Opens inline buttons: One Message or Message Range |

## 👋 Start welcome and latest-panel rule

- Open [@ChanRelayBot](https://t.me/ChanRelayBot) and send `/start` to begin.
- `/start` sends a compact welcome card with **⚙️ Open Panel** and **❓ Help**.
- `/help` opens a compact command guide inside your own latest panel.
- When `/start` is sent again, the bot creates a **new** card and moves all future copy/delete progress to that new card.
- Old panels remain unchanged. Tapping an old button shows a safe warning instead of moving the live task back to it.

## 💬 One-message panel

The detailed live card appears only while that user's copy/delete task is **Running** or **Paused**:

```text
▤ CHANNEL COPIER
├ 🟢 RUNNING  •  35.4%
├ ■■■■▥□□□□□□□  752 / 2,123
├ ✅ 710 copied  •  ⏭ 41 skipped
├ 📥 Next 752  •  ⚡ 3.42/s
├ ⏳ 6m 18s  •  🕒 3m 44s
├ 🎯 1 → 2,123  •  ⚡ Balanced
├ 📥 <SOURCE_CHANNEL>
└ 📤 <TARGET_CHANNEL>
```

When no task is active, the bot collapses the card instead of showing empty `0 / 0`, speed, ETA, range, or channel lines:

```text
▤ CHANNEL COPIER
├ 🔵 READY
└ ⚙️ Configure a task when you are ready.
```

Progress bar: `■` full, `□` empty, and `▤ ▥ ▦ ▧ ▨ ▩` is one partial cell.

## 🧹 Clean flow

Send `/clean` → choose **🗑 Source**, **🗑 Target**, or **🗑 Range** → confirm.

Only that saved field and that user's task counters are reset. Every confirmation has **✕ Cancel**.

## 🗑 Delete flow

Send `/delete` → choose **🗑 One Message** or **🎯 Message Range** → choose Source or Target → send the requested message ID/range → review warning → press **🗑 CONFIRM DELETE**.

Deletion is always bounded and always requires confirmation. The bot needs **Delete Messages** administrator permission in the selected channel.

## ☁️ Hugging Face Docker Space setup

Create a Docker Space, push these files, then add these **Secrets** in Space Settings:

```env
BOT_TOKEN=<YOUR_BOT_TOKEN>
API_ID=<YOUR_TELEGRAM_API_ID>
API_HASH=<YOUR_TELEGRAM_API_HASH>
```

Optional variables/secrets:

```env
ALLOW_ALL_USERS=true
MAX_ACTIVE_JOBS=3
OWNER_ID=0
DATA_DIR=/app/data
PYROGRAM_IPV6=false
LOG_LEVEL=INFO

# Optional force subscription — one public channel username is enough
FORCE_SUB_CHANNEL=@TharinduHub
```

`OWNER_ID` is optional. In multi-user mode it does not lock the bot; it only lets an old one-user SQLite state migrate to that account.

## 📱 Termux setup

```bash
pkg update -y && pkg upgrade -y
pkg install python python-pip git tmux -y
python -m pip install --no-cache-dir -r requirements.txt
cp .env.example .env
nano .env
python space_main.py
```

Do not run `python -m pip install --upgrade pip` on Termux.

## 📁 Structure

```text
📦 telegram-channel-copier/
├── 🐍 space_main.py          # Space / local entry point
├── 🐳 Dockerfile             # Hugging Face Docker runtime
├── 📜 requirements.txt        # Python packages
├── ⚙️ .env.example           # placeholders only
├── 📖 README.md               # this guide
├── 💬 CHANNEL_WELCOME.md      # ready-to-post channel message
├── 🎨 assets/                  # public profile artwork
│   └── 🟣 chan-relay-bot-logo.png
└── 📂 app/
    ├── 🤖 bot.py             # per-user commands + inline controls
    ├── 🗃️ store.py           # isolated SQLite profiles/jobs
    ├── ⚙️ workers.py          # copy/delete workers per user
    ├── 🎨 ui.py               # compact panel renderer
    ├── 🔌 api.py              # Pyrogram MTProto bridge
    ├── 🧩 config.py           # environment settings
    └── 🛠️ pyrogram_compat.py # newer private-channel ID support
```

## 🔒 Privacy notes

- Never commit `.env`, `data/`, session files, logs, or SQLite files.
- Each profile is keyed by Telegram user ID and is not shown in another user's private panel.
- Free Hugging Face storage may reset after a Space restart; note the **Next ID** before rebuilding a running Space.
