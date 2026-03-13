#!/usr/bin/env python3
"""
Appodeal Pulse — Content Curator & HTML Generator

Reads collected Slack data, uses Claude AI to curate the most interesting
content, and generates the SLIDES JSON for the HTML slideshow.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import anthropic

import config
from export_pptx import export_pptx
from export_google_slides import upload_to_google_slides

# ── Accent colors from BidMachine palette ───────────────────────

ACCENT_COLORS = {
    "birthday":    {"accent": "#FFB72B", "gradient": "linear-gradient(135deg, #FFB72B 0%, #FFCC66 100%)"},
    "win":         {"accent": "#12DF58", "gradient": "linear-gradient(135deg, #12DF58 0%, #71F49D 100%)"},
    "clap":        {"accent": "#5D2CAC", "gradient": "linear-gradient(135deg, #5D2CAC 0%, #8B5DD5 100%)"},
    "newjoin":     {"accent": "#00FFD1", "gradient": "linear-gradient(135deg, #00FFD1 0%, #66FFE3 100%)"},
    "event":       {"accent": "#E84039", "gradient": "linear-gradient(135deg, #E84039 0%, #EF7A76 100%)"},
    "milestone":   {"accent": "#1667EF", "gradient": "linear-gradient(135deg, #1667EF 0%, #70A1F5 100%)"},
    "reading":     {"accent": "#5D2CAC", "gradient": "linear-gradient(135deg, #5D2CAC 0%, #A885E0 100%)"},
    "officelife":  {"accent": "#00FFD1", "gradient": "linear-gradient(135deg, #00FFD1 0%, #99FFEC 100%)"},
    "celebration": {"accent": "#FFB72B", "gradient": "linear-gradient(135deg, #FFB72B 0%, #FFDD99 100%)"},
    "pet":         {"accent": "#12DF58", "gradient": "linear-gradient(135deg, #12DF58 0%, #A1F7BE 100%)"},
}

# ── Extra accent pool for variety ───────────────────────────────

EXTRA_ACCENTS = [
    {"accent": "#10B981", "gradient": "linear-gradient(135deg, #10B981 0%, #34D399 100%)"},
    {"accent": "#EC4899", "gradient": "linear-gradient(135deg, #EC4899 0%, #F9A8D4 100%)"},
    {"accent": "#0EA5E9", "gradient": "linear-gradient(135deg, #0EA5E9 0%, #38BDF8 100%)"},
    {"accent": "#F97316", "gradient": "linear-gradient(135deg, #F97316 0%, #FB923C 100%)"},
    {"accent": "#14B8A6", "gradient": "linear-gradient(135deg, #14B8A6 0%, #5EEAD4 100%)"},
    {"accent": "#D946EF", "gradient": "linear-gradient(135deg, #D946EF 0%, #E879F9 100%)"},
    {"accent": "#EF4444", "gradient": "linear-gradient(135deg, #EF4444 0%, #F87171 100%)"},
    {"accent": "#6366F1", "gradient": "linear-gradient(135deg, #6366F1 0%, #818CF8 100%)"},
    {"accent": "#F59E0B", "gradient": "linear-gradient(135deg, #F59E0B 0%, #FBBF24 100%)"},
    {"accent": "#22C55E", "gradient": "linear-gradient(135deg, #22C55E 0%, #4ADE80 100%)"},
]


# ── Load collected data ─────────────────────────────────────────

def load_content():
    path = os.path.join(config.DATA_DIR, "content.json")
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Run collect.py first.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Prepare channel summaries for AI prompt ─────────────────────

def summarize_channels(content):
    """Create a compact text summary of all channel messages for the AI."""
    parts = []
    for ch_name, ch_data in content["channels"].items():
        msgs = ch_data.get("messages", [])
        if not msgs:
            continue
        parts.append(f"\n### #{ch_name} ({len(msgs)} messages)")
        for m in msgs[:30]:  # Limit to avoid token overflow
            reactions_str = ""
            if m.get("reactions"):
                reactions_str = " | Reactions: " + ", ".join(
                    f":{r['emoji']}: ×{r['count']}" for r in m["reactions"]
                )
            links_str = ""
            if m.get("links"):
                links_str = " | Links: " + ", ".join(
                    f"[{l['title']}]({l['url']})" for l in m["links"]
                )
            images_str = f" | {len(m['images'])} image(s)" if m.get("images") else ""
            text = m["text"][:500] if m.get("text") else "(no text)"
            parts.append(
                f"- [{m['user']}] {text}{reactions_str}{links_str}{images_str}"
            )
    return "\n".join(parts)


def build_avatar_lookup(content):
    """Build name → avatar URL mapping from collected data."""
    avatars = content.get("user_avatars", {})
    # Also scan messages for any avatars not in the top-level dict
    for ch_data in content.get("channels", {}).values():
        for msg in ch_data.get("messages", []):
            name = msg.get("user", "")
            avatar = msg.get("user_avatar", "")
            if name and avatar and name not in avatars:
                avatars[name] = avatar
    return avatars


# ── AI Curation via Claude ──────────────────────────────────────

SYSTEM_PROMPT = """You are the content curator for "Appodeal PULSE" — a daily company wall newspaper / digital signage displayed on office TVs.

Your job: analyze raw Slack messages and produce a JSON array of slide objects for a beautiful auto-rotating slideshow.

SLIDE TYPES (use exact "type" values):
1. "birthday" — birthday celebrations. ONLY if someone has a birthday TODAY or YESTERDAY. Skip completely otherwise — no "recent birthdays" or past dates.
2. "win" — achievements, wins, metrics improvements
3. "clap" — peer recognition / kudos from #claps channel
4. "newjoin" — new team members joining
5. "event" — upcoming events / conferences
6. "milestone" — company milestones, big numbers
7. "reading" — interesting articles/links shared ONLY from #to_read channel
8. "officelife" — fun office moments, quotes, culture
9. "celebration" — weekly celebrations / rituals
10. "event" — also use for Book Club announcements, corporate initiatives from #general (NOT "reading"!)

REQUIRED FIELDS per type:
birthday: emoji, accent, gradient, title, name, date, message, teamNote
win: emoji, accent, gradient, title, who, stat, statUnit, headline, description, takeaway
clap: emoji, accent, gradient, title, count, from, to (array), reason, values (array)
newjoin: emoji, accent, gradient, title, name, role, team, quote
event: emoji, accent, gradient, title, eventName, date, description, organizer
milestone: emoji, accent, gradient, title, headline, description, stat, statLabel
reading: emoji, accent, gradient, title, articles (array of {title, sharedBy, desc, reactions}), channel
officelife: emoji, accent, gradient, title, headline, quote, author, reactions, channel
celebration: emoji, accent, gradient, title, headline, prompt1, prompt2, coreValue, channel

AVATAR SUPPORT — IMPORTANT:
- A user_avatars dictionary mapping names to Slack profile picture URLs will be provided
- For slides that feature specific people (birthday, newjoin, clap, win, officelife), add an "avatar" field with their profile picture URL
- Use EXACT names as keys to look up avatars from the provided dictionary
- If no avatar URL is available for a person, omit the "avatar" field

CRITICAL RULES:
- SKIP birthday slides entirely if no one has a birthday TODAY or YESTERDAY. Never show birthdays from last week or earlier
- SKIP any slide type that has no fresh content — NEVER invent fake content
- Write in English, concise and punchy — displayed on big screens
- Use varied emojis for different slides
- Warm, positive, engaging tone
- For "win" slides, extract specific metrics/numbers when available
- For "clap" slides, extract company values mentioned (e.g., "We work TOGETHER to SERVE OTHERS")
- For "reading", pick the 2-3 most interesting articles — ONLY from #to_read channel
- NEVER mix different things into one "reading" slide. Book Club = "event" type. Article suggestions from #to_read = "reading" type. These are SEPARATE slides
- Order slides for maximum engagement: start exciting, mix types, end with a call-to-action
- Aim for 15-20 slides. Be creative — split big topics into multiple slides, add more claps, more wins
- If a channel has multiple interesting messages, create separate slides for each
- Create at least one "officelife" or "celebration" slide to keep it warm and human
- Return ONLY the JSON array, no markdown, no explanation

CONTENT FILTER — NEVER include:
- Terminations, layoffs, firings, people leaving the company
- Demotions or role downgrades
- Negative HR actions or disciplinary matters
- Any sensitive personnel changes
- Only show POSITIVE content: birthdays, wins, recognition, events, new joiners"""

DEEP_ANALYSIS_ADDENDUM_STATIC = """
ADDITIONAL CONTEXT — COMPANY METRICS & STRATEGY (from leadership meetings):
Include 2-4 extra slides based on this strategic context. Use "milestone" or "win" type.
Pick the most impressive/inspiring facts:

- Company: ~$100M gross profit, $20M EBITDA, 40% YoY growth projected
- Vision: building toward $50B company, 1,500 employees, 100 studios
- AI Strategy: every employee will manage 5-10 AI agents within 3-6 months
- OKR Auditor checks 1,000+ individual OKRs daily via AI
- Daria AI Bot saves $4k/week analyzing app reviews
- Gaming turned profitable in 2025
- Infinite Minesweeper: 61% retention (Apple benchmark ERA: 151-160%)
- Solitaire v540: +21.67% D7 retention
- Crossword: ROAS exceeded 200%
- Fraud reduced from 22% to under 4% with dynamic SDK signatures
- Sales: 8 deals closed / $390k net revenue in one week
- CEO mandate: "Build. Ship. Improve." — shift from requirements to pull request mentality
- AI Advent Challenge: 20-day marathon, 6 heroes completed all challenges
- Daily yoga at 13:10 CET by Anna Kolyada (office + online streaming)
- Book Club "Passionate Curiosity": 140+ participants
- BidMachine merch (sweatshirts) being designed

DO NOT repeat these facts if they already appeared in Slack content above. Only add NEW slides."""


def build_fireflies_section(content):
    """Build dynamic meeting insights section from Fireflies data."""
    meetings = content.get("fireflies_meetings", [])
    if not meetings:
        return ""

    parts = ["""
RECENT MEETING INSIGHTS (from Fireflies transcripts):
Create 2-4 slides from these meeting highlights. Use "milestone", "win", or "event" type.

FIREFLIES CONTENT RULES — STRICTLY FOLLOW:
1. NEVER quote anyone directly from meetings — always paraphrase and summarize
2. NEVER include profanity, harsh language, aggressive tone, or emotional outbursts — even if present in the source. Strip all that out completely
3. BE REAL, NOT SUGARCOATED — you CAN name problems as problems, challenges as challenges. Don't pretend everything is perfect. But ALWAYS add a constructive angle: "here's the challenge AND here's what we're doing about it" or "this is an opportunity to grow"
4. TONE: honest reality check delivered in a kind, respectful way. Like a smart friend who tells you the truth but believes in you
5. Focus on: strategic decisions, wins, challenges being tackled, new initiatives, team achievements, product milestones, goals, learnings from setbacks
6. SKIP meetings about: HR topics, performance reviews, individual feedback, salary discussions, disciplinary matters, personal conflicts
7. Do NOT attribute specific opinions, criticism, or controversial statements to named individuals
8. Every slide should leave people informed AND motivated — not anxious or discouraged
"""]

    for m in meetings:
        title = m.get("title", "")
        date = m.get("date", "")[:10]
        participants = m.get("participant_count", 0)
        duration = m.get("duration_min", 0)
        overview = m.get("overview", "")
        bullets = m.get("bullets", "")
        keywords = ", ".join(m.get("keywords", [])[:8])

        # Skip very short meetings or 1:1s
        if participants < 3 or duration < 10:
            continue

        parts.append(f"\n--- Meeting: {title} ({date}, {participants} participants, {duration:.0f} min) ---")
        if overview:
            parts.append(f"Summary: {overview[:500]}")
        if bullets:
            parts.append(f"Key points: {bullets[:500]}")
        if keywords:
            parts.append(f"Keywords: {keywords}")

    if len(parts) <= 1:
        return ""

    return "\n".join(parts)


def is_deep_analysis_day():
    """Check if today is a deep analysis day (Mon/Wed/Fri)."""
    return datetime.now().weekday() in config.DEEP_ANALYSIS_DAYS


def curate_with_ai(channel_summary, avatar_lookup=None, content=None):
    """Use Claude to curate content and generate SLIDES JSON."""
    api_key = config.ANTHROPIC_API_KEY
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    today_dt = datetime.now()
    today = today_dt.strftime("%A, %B %d, %Y")
    day_name = today_dt.strftime("%A")
    deep = is_deep_analysis_day()

    # Build avatar section for AI prompt
    avatar_section = ""
    if avatar_lookup:
        avatar_lines = json.dumps(avatar_lookup, ensure_ascii=False, indent=2)
        avatar_section = f"""

USER AVATARS (name → Slack profile picture URL):
{avatar_lines}

Use these URLs as the "avatar" field in slides that feature specific people.
"""

    user_prompt = f"""Today is {today} ({day_name}).

Here are the raw Slack messages from the last {config.LOOKBACK_HOURS} hours across our channels:

{channel_summary}
{avatar_section}"""

    # Add Fireflies meeting insights (dynamic)
    fireflies_section = build_fireflies_section(content) if content else ""
    if fireflies_section:
        user_prompt += f"\n{fireflies_section}\n"
        print(f"  Including Fireflies meeting insights")

    if deep:
        user_prompt += f"\n{DEEP_ANALYSIS_ADDENDUM_STATIC}\n"
        print(f"  Deep analysis day ({day_name}) — including static strategy context")
    else:
        print(f"  Regular day ({day_name})")

    user_prompt += "\nGenerate the SLIDES JSON array for today's Appodeal PULSE. Return ONLY valid JSON array."

    print("  Calling Claude API for content curation...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON array from response (handle markdown code blocks)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    return json.loads(text)


# ── Apply accent colors ─────────────────────────────────────────

def apply_accents(slides):
    """Ensure all slides have accent colors from our palette."""
    extra_idx = 0
    for slide in slides:
        slide_type = slide.get("type", "")
        if slide_type in ACCENT_COLORS:
            defaults = ACCENT_COLORS[slide_type]
        else:
            defaults = EXTRA_ACCENTS[extra_idx % len(EXTRA_ACCENTS)]
            extra_idx += 1

        if "accent" not in slide:
            slide["accent"] = defaults["accent"]
        if "gradient" not in slide:
            slide["gradient"] = defaults["gradient"]

    return slides


def _find_avatar(name, avatar_lookup):
    """Find avatar URL for a person name with fuzzy matching."""
    if not name or not avatar_lookup:
        return ""
    # Exact match
    if name in avatar_lookup:
        return avatar_lookup[name]
    # Case-insensitive match
    name_lower = name.lower()
    for k, v in avatar_lookup.items():
        if k.lower() == name_lower:
            return v
    # First name match (e.g., "Dima" matches "Dima Chernov")
    first = name.split()[0] if name else ""
    if first and first in avatar_lookup:
        return avatar_lookup[first]
    # Partial: avatar key starts with name or name starts with avatar key
    for k, v in avatar_lookup.items():
        if k.startswith(name) or name.startswith(k):
            return v
    return ""


def inject_avatars(slides, avatar_lookup):
    """Post-process slides to inject avatar URLs for ALL people mentioned."""
    if not avatar_lookup:
        return slides

    for slide in slides:
        stype = slide.get("type", "")

        # Birthday & NewJoin — main person
        if stype in ("birthday", "newjoin") and not slide.get("avatar"):
            avatar = _find_avatar(slide.get("name", ""), avatar_lookup)
            if avatar:
                slide["avatar"] = avatar

        # Win — who did it
        if stype == "win" and not slide.get("avatar"):
            avatar = _find_avatar(slide.get("who", ""), avatar_lookup)
            if avatar:
                slide["avatar"] = avatar

        # OfficeLife — author
        if stype == "officelife" and not slide.get("avatar"):
            avatar = _find_avatar(slide.get("author", ""), avatar_lookup)
            if avatar:
                slide["avatar"] = avatar

        # Clap — from person
        if stype == "clap" and not slide.get("fromAvatar"):
            avatar = _find_avatar(slide.get("from", ""), avatar_lookup)
            if avatar:
                slide["fromAvatar"] = avatar

        # Clap — to people (add avatars to each recipient)
        if stype == "clap" and slide.get("to"):
            to_with_avatars = []
            for person in slide["to"]:
                if isinstance(person, str):
                    avatar = _find_avatar(person, avatar_lookup)
                    to_with_avatars.append({
                        "name": person,
                        "avatar": avatar,
                    })
                elif isinstance(person, dict):
                    if not person.get("avatar"):
                        person["avatar"] = _find_avatar(person.get("name", ""), avatar_lookup)
                    to_with_avatars.append(person)
            slide["to"] = to_with_avatars

        # Event — organizer
        if stype == "event" and not slide.get("organizerAvatar"):
            avatar = _find_avatar(slide.get("organizer", ""), avatar_lookup)
            if avatar:
                slide["organizerAvatar"] = avatar

        # Reading — article sharers
        if stype == "reading" and slide.get("articles"):
            for article in slide["articles"]:
                if not article.get("sharedByAvatar"):
                    avatar = _find_avatar(article.get("sharedBy", ""), avatar_lookup)
                    if avatar:
                        article["sharedByAvatar"] = avatar

    return slides


# ── Generate final HTML ─────────────────────────────────────────

def generate_html(slides):
    """Inject SLIDES JSON into the HTML template."""
    template_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    slides_json = json.dumps(slides, ensure_ascii=False, indent=2)
    html = html.replace("%%SLIDES_JSON%%", slides_json)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(config.OUTPUT_DIR, "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Generated {output_path}")
    return output_path


# ── Fallback: generate without AI ───────────────────────────────

def generate_fallback_slides(content):
    """Generate basic slides without AI if API is unavailable."""
    slides = []
    today = datetime.now().strftime("%B %d")

    # Check birthdays channel
    birthday_msgs = content["channels"].get("birthdays", {}).get("messages", [])
    for msg in birthday_msgs:
        text = msg.get("text", "")
        if "birthday" in text.lower() or "happy" in text.lower():
            # Try to extract name
            name = msg.get("user", "Team Member")
            slides.append({
                "type": "birthday",
                "emoji": "🎂",
                **ACCENT_COLORS["birthday"],
                "title": "Happy Birthday!",
                "name": name,
                "date": today,
                "message": "Wishing you an amazing day filled with joy and celebration!",
                "teamNote": "With love, Your Appodeal Team 💜",
            })

    # Check general for news
    general_msgs = content["channels"].get("general", {}).get("messages", [])
    for msg in sorted(general_msgs, key=lambda m: m.get("reaction_count", 0), reverse=True)[:3]:
        text = msg.get("text", "")
        if len(text) > 20:
            slides.append({
                "type": "officelife",
                "emoji": "📢",
                **ACCENT_COLORS["officelife"],
                "title": "From #general",
                "headline": text[:80] + ("..." if len(text) > 80 else ""),
                "quote": text[:300],
                "author": msg.get("user", ""),
                "reactions": "",
                "channel": "#general",
            })

    # Check pets
    pet_msgs = content["channels"].get("appodeal_pets", {}).get("messages", [])
    for msg in pet_msgs[:1]:
        if msg.get("images") or msg.get("text"):
            slides.append({
                "type": "officelife",
                "emoji": "🐾",
                **ACCENT_COLORS["pet"],
                "title": "Pet of the Day",
                "headline": "Our furry friends!",
                "quote": msg.get("text", "Look at this cutie!")[:200],
                "author": msg.get("user", ""),
                "reactions": "",
                "channel": "#appodeal_pets",
            })

    # Check to_read for articles
    reading_msgs = content["channels"].get("to_read", {}).get("messages", [])
    articles = []
    for msg in reading_msgs[:3]:
        if msg.get("links"):
            link = msg["links"][0]
            articles.append({
                "title": link.get("title", "Interesting Read"),
                "sharedBy": msg.get("user", ""),
                "desc": link.get("text", msg.get("text", ""))[:150],
                "reactions": "",
            })
    if articles:
        slides.append({
            "type": "reading",
            "emoji": "📚",
            **ACCENT_COLORS["reading"],
            "title": "What We're Reading",
            "articles": articles,
            "channel": "#to_read",
        })

    return slides if slides else [{
        "type": "celebration",
        "emoji": "☀️",
        **ACCENT_COLORS["celebration"],
        "title": "Good Morning, Appodeal!",
        "headline": "A New Day Begins",
        "prompt1": "🌱 What are you working on today?",
        "prompt2": "💡 What's one thing you're grateful for?",
        "coreValue": "Every day is a chance to make an impact.",
        "channel": "#general",
    }]


# ── Entry point ─────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Appodeal Pulse — Generating slides")
    print("=" * 50)

    content = load_content()
    channel_summary = summarize_channels(content)
    avatar_lookup = build_avatar_lookup(content)
    print(f"  Found {len(avatar_lookup)} user avatars")

    if config.ANTHROPIC_API_KEY:
        try:
            slides = curate_with_ai(channel_summary, avatar_lookup, content)
            slides = apply_accents(slides)
            slides = inject_avatars(slides, avatar_lookup)
            print(f"  AI generated {len(slides)} slides")
        except Exception as e:
            print(f"  AI curation failed: {e}")
            print("  Falling back to basic generation...")
            slides = generate_fallback_slides(content)
    else:
        print("  No ANTHROPIC_API_KEY — using fallback generation")
        slides = generate_fallback_slides(content)

    # Save slides JSON separately for debugging
    slides_path = os.path.join(config.DATA_DIR, "slides.json")
    with open(slides_path, "w", encoding="utf-8") as f:
        json.dump(slides, f, ensure_ascii=False, indent=2)
    print(f"  Saved slides to {slides_path}")

    # Generate final HTML
    output = generate_html(slides)

    # Export to PPTX archive
    pptx_path = None
    try:
        pptx_path = export_pptx(slides)
        print(f"  Archived presentation → {pptx_path}")
    except Exception as e:
        print(f"  PPTX export failed: {e}")

    # Upload to Google Slides (if credentials configured)
    if pptx_path:
        try:
            upload_to_google_slides(pptx_path)
        except Exception as e:
            print(f"  [Google Slides] Upload failed: {e}")

    print(f"\n  Done! Open {output} in a browser.")
