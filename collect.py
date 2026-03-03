#!/usr/bin/env python3
"""
Appodeal Pulse — Slack Data Collector

Collects messages from target Slack channels over the last 24 hours
and saves structured content to data/content.json
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import config

# ── Slack client setup ──────────────────────────────────────────

def get_slack_client():
    token = config.SLACK_BOT_TOKEN
    if not token:
        print("ERROR: SLACK_BOT_TOKEN not set. Export it as environment variable.")
        sys.exit(1)
    return WebClient(token=token)


# ── Message fetching ────────────────────────────────────────────

def fetch_channel_messages(client, channel_id, channel_name, hours=24):
    """Fetch messages from a channel within the lookback window."""
    oldest = str((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
    messages = []

    try:
        result = client.conversations_history(
            channel=channel_id,
            oldest=oldest,
            limit=100,
        )
        for msg in result.get("messages", []):
            if msg.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
                continue

            # Resolve user name
            user_name = resolve_user(client, msg.get("user", ""))

            # Extract reactions
            reactions = []
            for r in msg.get("reactions", []):
                reactions.append({
                    "emoji": r["name"],
                    "count": r["count"],
                })

            # Extract image attachments
            images = []
            for f in msg.get("files", []):
                if f.get("mimetype", "").startswith("image/"):
                    images.append({
                        "url": f.get("url_private", ""),
                        "thumb": f.get("thumb_480", f.get("thumb_360", "")),
                        "name": f.get("name", ""),
                    })

            # Extract link attachments
            links = []
            for att in msg.get("attachments", []):
                if att.get("original_url") or att.get("title_link"):
                    links.append({
                        "url": att.get("original_url", att.get("title_link", "")),
                        "title": att.get("title", ""),
                        "text": att.get("text", "")[:300] if att.get("text") else "",
                    })

            messages.append({
                "channel": channel_name,
                "channel_id": channel_id,
                "user": user_name,
                "user_id": msg.get("user", ""),
                "text": msg.get("text", ""),
                "ts": msg.get("ts", ""),
                "timestamp": datetime.fromtimestamp(
                    float(msg.get("ts", "0")), tz=timezone.utc
                ).isoformat(),
                "reactions": reactions,
                "reaction_count": sum(r["count"] for r in reactions),
                "images": images,
                "links": links,
                "thread_reply_count": msg.get("reply_count", 0),
            })

    except SlackApiError as e:
        print(f"  Warning: Could not fetch #{channel_name}: {e.response['error']}")

    return messages


# ── User resolution cache ───────────────────────────────────────

_user_cache = {}

def resolve_user(client, user_id):
    """Resolve Slack user ID to display name."""
    if not user_id:
        return "Unknown"
    if user_id in _user_cache:
        return _user_cache[user_id]
    try:
        info = client.users_info(user=user_id)
        profile = info["user"]["profile"]
        name = profile.get("real_name") or profile.get("display_name") or user_id
        _user_cache[user_id] = name
        return name
    except SlackApiError:
        _user_cache[user_id] = user_id
        return user_id


# ── Main collection pipeline ────────────────────────────────────

def collect_all():
    client = get_slack_client()
    all_content = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": config.LOOKBACK_HOURS,
        "channels": {},
    }

    for name, channel_id in config.SLACK_CHANNELS.items():
        print(f"  Collecting #{name} ({channel_id})...")
        messages = fetch_channel_messages(
            client, channel_id, name, config.LOOKBACK_HOURS
        )
        all_content["channels"][name] = {
            "channel_id": channel_id,
            "message_count": len(messages),
            "messages": messages,
        }
        print(f"    → {len(messages)} messages")
        time.sleep(0.5)  # Rate limit courtesy

    return all_content


def save_content(content):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = os.path.join(config.DATA_DIR, "content.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved to {path}")
    return path


# ── Entry point ─────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Appodeal Pulse — Collecting Slack data")
    print("=" * 50)
    content = collect_all()

    total = sum(
        ch["message_count"] for ch in content["channels"].values()
    )
    print(f"\n  Total: {total} messages from {len(content['channels'])} channels")

    save_content(content)
    print("  Done!")
