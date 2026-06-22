"""Compatibility patch for newer Telegram channel IDs on Pyrogram 2.0.106.

Pyrogram 2.0.106 has legacy channel-ID limits. Telegram channel IDs created after
that range can be valid but get rejected locally before Pyrogram sends a request.
This updates the in-memory limits only; it does not bypass Telegram permissions.
"""
from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)

# Telegram's newer peer-ID ranges. Keep in sync with Pyrogram's post-2.0.106 fix.
NEW_MIN_CHANNEL_ID = -1007852516352
NEW_MIN_CHAT_ID = -999999999999


def apply_peer_id_compat() -> None:
    """Allow Pyrogram 2.0.106 to classify current private channel IDs correctly."""
    try:
        import pyrogram.utils as utils
    except Exception as exc:  # pragma: no cover - only relevant during broken installs
        LOGGER.warning("Could not apply Pyrogram peer-ID compatibility patch: %s", exc)
        return

    old_channel = int(getattr(utils, "MIN_CHANNEL_ID", NEW_MIN_CHANNEL_ID))
    old_chat = int(getattr(utils, "MIN_CHAT_ID", NEW_MIN_CHAT_ID))
    utils.MIN_CHANNEL_ID = min(old_channel, NEW_MIN_CHANNEL_ID)
    utils.MIN_CHAT_ID = min(old_chat, NEW_MIN_CHAT_ID)

    LOGGER.info(
        "Applied Pyrogram newer-channel-ID compatibility: MIN_CHANNEL_ID %s → %s; "
        "MIN_CHAT_ID %s → %s.",
        old_channel,
        utils.MIN_CHANNEL_ID,
        old_chat,
        utils.MIN_CHAT_ID,
    )
