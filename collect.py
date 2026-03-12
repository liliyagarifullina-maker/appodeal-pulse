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

            # Filter out sensitive content (terminations, demotions, etc.)
            text_lower = (msg.get("text") or "").lower()
            BLOCKED_KEYWORDS = [
                "fired", "terminated", "termination", "laid off", "layoff",
                "let go", "last day", "leaving the company", "no longer with",
                "demoted", "demotion", "stepping down", "role change",
                "уволен", "увольнение", "сокращ", "понижен", "понижение",
                "последний день", "покидает компанию",
            ]
            if any(kw in text_lower for kw in BLOCKED_KEYWORDS):
                continue

            # Resolve user name and avatar
            user_info = resolve_user(client, msg.get("user", ""))
            user_name = user_info["name"]
            user_avatar = user_info["avatar"]

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
                "user_avatar": user_avatar,
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

_user_cache = {}  # user_id -> {"name": str, "avatar": str}

def resolve_user(client, user_id):
    """Resolve Slack user ID to display name and profile picture."""
    if not user_id:
        return {"name": "Unknown", "avatar": ""}
    if user_id in _user_cache:
        return _user_cache[user_id]
    try:
        info = client.users_info(user=user_id)
        profile = info["user"]["profile"]
        name = profile.get("real_name") or profile.get("display_name") or user_id
        # Get highest-res profile picture available
        avatar = (
            profile.get("image_192")
            or profile.get("image_72")
            or profile.get("image_48")
            or ""
        )
        _user_cache[user_id] = {"name": name, "avatar": avatar}
        return _user_cache[user_id]
    except SlackApiError:
        _user_cache[user_id] = {"name": user_id, "avatar": ""}
        return _user_cache[user_id]


# ── Fetch all workspace users ──────────────────────────────────

def fetch_all_users(client):
    """Fetch ALL workspace users and their avatars via users.list API.
    Returns dict: name → avatar_url (for all ~300 employees).
    """
    all_avatars = {}
    cursor = None
    page = 0

    while True:
        try:
            kwargs = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor

            result = client.users_list(**kwargs)
            members = result.get("members", [])
            page += 1

            for user in members:
                # Skip bots, deleted users, and Slackbot
                if user.get("is_bot") or user.get("deleted") or user.get("id") == "USLACKBOT":
                    continue

                profile = user.get("profile", {})
                name = (
                    profile.get("real_name")
                    or profile.get("display_name")
                    or user.get("name", "")
                )
                if not name:
                    continue

                # Get best available avatar (prefer larger)
                avatar = (
                    profile.get("image_192")
                    or profile.get("image_72")
                    or profile.get("image_48")
                    or ""
                )
                if avatar and "gravatar" not in avatar:
                    all_avatars[name] = avatar

                    # Also store by first name for fuzzy matching
                    first_name = name.split()[0] if name else ""
                    if first_name and first_name not in all_avatars:
                        all_avatars[first_name] = avatar

                    # Also store by Slack username (handle)
                    username = user.get("name", "")
                    if username:
                        all_avatars[username] = avatar

            # Pagination
            next_cursor = result.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            cursor = next_cursor
            time.sleep(0.3)  # Rate limit

        except SlackApiError as e:
            print(f"  Warning: users.list failed: {e.response['error']}")
            break

    print(f"  Loaded {len(all_avatars)} user avatars from workspace (page {page})")
    return all_avatars


# ── Main collection pipeline ────────────────────────────────────

def collect_all():
    client = get_slack_client()
    all_content = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": config.LOOKBACK_HOURS,
        "channels": {},
    }

    # First: load ALL workspace users for avatar lookup
    print("  Loading all workspace users...")
    all_avatars = fetch_all_users(client)

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

    # Merge: workspace-wide avatars + message-level avatars
    all_content["user_avatars"] = all_avatars
    # Also add any from message cache (in case users.list missed someone)
    for v in _user_cache.values():
        if v.get("avatar") and v["name"] not in all_content["user_avatars"]:
            all_content["user_avatars"][v["name"]] = v["avatar"]

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
