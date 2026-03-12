"""
Appodeal Pulse — Configuration

All secrets come from environment variables.
Set them in .env locally or in Render dashboard for production.
"""

import os

# ── Secrets (from environment) ──────────────────────────────────

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── Slack channels to monitor ───────────────────────────────────

SLACK_CHANNELS = {
    "general":        "C039760M5",
    "general-chat":   "C010UQ0QP5K",
    "birthdays":      "C87RRF63S",
    "to_read":        "C4XGGGLMV",
    "claps":          "C084KUM8W79",
}

# ── Content settings ────────────────────────────────────────────

LOOKBACK_HOURS = 72          # 3 days — captures more content
MAX_SLIDES = 25
MIN_SLIDES = 15              # AI should aim for at least this many

# Fireflies deep insights included every day for richer content
DEEP_ANALYSIS_DAYS = [0, 1, 2, 3, 4, 5, 6]  # Every day

# ── Paths ───────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMPLATE_PATH = os.path.join(BASE_DIR, "index.html")

# ── Server ──────────────────────────────────────────────────────

PORT = int(os.environ.get("PORT", 8080))
