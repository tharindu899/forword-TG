# Changelog

## 🎯 Optional delete range

- 🗑 Added **Use Copy Range** after choosing the source or target delete channel.
- 🎯 Added **Custom Range** as an optional one-time override for deletion.
- 🔒 Deletion remains bounded and always requires the final **🗑 CONFIRM DELETE** button.
- ✕ Back and Cancel remain available through each delete step.


## ✨ Clear setup controls

- Added **🗑 Source**, **🗑 Target**, and **🗑 Range** buttons to the one-message setup panel.
- The buttons reset only the selected saved setting and reset stale copy counters safely.
- Clear actions are blocked while a copy is running; pause first to prevent accidental changes.
- Kept the compact `▤ / ├ / └` message layout and the true `■ / □` progress bar.

# True Fill Progress Bar

- Uses `■` for a fully completed progress cell.
- Uses `□` for an empty progress cell.
- Uses exactly one intermediate cell from `▤ ▥ ▦ ▧ ▨ ▩` when a cell is partly complete.
- Avoids rounding the display up early, so the bar matches the shown percentage more closely.

# Branch + Emoji Panel

- Keeps the `▤` heading and `├ / └` compact line structure.
- Removes `▥`, `▨`, and `▩` from labels and setup text.
- Reserves `▦ / ▧` for the progress bar only.
- Uses emojis for every regular status row.

# Changelog

## Sri Lanka Log Time

- All container, Pyrogram, copier, and health logs now use **Sri Lankan Standard Time** (`Asia/Colombo`, UTC+05:30).
- Log timestamps include the `SLST` label, for example: `2026-06-22 20:18:59,774 SLST`.
- Added `TZ=Asia/Colombo` to the Docker runtime environment.

## Compact One-Card UI

- Reworked the bot PM into a single editable compact control card.
- Setup screens now edit the same card instead of sending prompts and confirmation messages.
- Input replies and slash commands are deleted when Telegram permits, keeping the PM clean.
- Added a compact status layout with aesthetic divider lines, emoji indicators, a progress bar, speed, ETA, and next source ID.
- Reduced visible slash commands to four essential commands.

## Unified branch-message style

- Every visible bot card now uses the same `▤` title with `├` and `└` rows.
- Setup, source/target/range/test prompts, speed screen, errors, access warning, pause, completion, and live progress all share one compact style.
- `▦` and `▧` remain reserved for the visual progress bar only.
- No rounded `╭ ╰ ━` frames are used.

## Peer-ID compatibility fix

- Fixed `400 PEER_ID_INVALID` for newer private channel IDs for recently created private channels when using Pyrogram 2.0.106.
- Added a startup compatibility patch for Pyrogram's legacy channel-ID range.
- Test now checks source and target separately and tells you exactly which channel needs bot access.
- Warm the MTProto peer cache from the bot's dialogs on every startup, so private-channel access hashes are available after a fresh Hugging Face rebuild.

## 📖 Documentation

- Added a full emoji file-tree map for repository files and private runtime files.
- Added upload / do-not-upload checklists to protect tokens, IDs, sessions, logs, and local data.
