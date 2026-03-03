#!/bin/bash
# Appodeal Pulse — Daily pipeline runner
# Collects Slack data → AI curation → Generates HTML slideshow

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  APPODEAL PULSE — Daily Update"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Step 1: Collect data from Slack
echo ""
echo "▸ Step 1/2: Collecting Slack data..."
python3 collect.py

# Step 2: Generate slides with AI + build HTML + export PPTX
echo ""
echo "▸ Step 2/2: Curating content & generating slides + PPTX..."
python3 generate.py

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Pulse updated! Open output/index.html"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
