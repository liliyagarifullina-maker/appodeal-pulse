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
import traceback
from datetime import datetime, timezone, timedelta

import anthropic

import config
from export_pptx import export_pptx
try:
    from export_google_slides import upload_to_google_slides
except ImportError:
    upload_to_google_slides = None

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

EXCLUDED_AUTHORS = {"liliya garifullina", "liliya"}


def _resolve_mentions(text, user_id_map):
    """Replace <@USERID> mentions with actual names so AI can read them."""
    import re
    def _replace(match):
        uid = match.group(1)
        info = user_id_map.get(uid, {})
        name = info.get("name", "") if isinstance(info, dict) else ""
        return f"@{name}" if name else match.group(0)
    return re.sub(r'<@([UW][A-Z0-9]+)>', _replace, text)


def summarize_channels(content):
    """Create a compact text summary of all channel messages for the AI."""
    user_id_map = _build_user_id_map(content)
    office_tz = timezone(timedelta(hours=config.OFFICE_TZ_OFFSET))

    parts = []
    for ch_name, ch_data in content["channels"].items():
        msgs = ch_data.get("messages", [])
        if not msgs:
            continue
        parts.append(f"\n### #{ch_name} ({len(msgs)} messages)")
        for m in msgs[:30]:  # Limit to avoid token overflow
            # Skip messages from excluded people (pre-filter before AI sees them)
            author = (m.get("user") or "").lower().strip()
            if author in EXCLUDED_AUTHORS:
                continue
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

            # Resolve <@USERID> mentions to real names (critical for birthdays!)
            text = _resolve_mentions(text, user_id_map)

            # For birthday channels: inject actual date from message timestamp
            # Ira posts "Dear @Name" on the birthday (or next workday for weekends)
            date_prefix = ""
            if ch_name in ("birthdays", "birthdays-notifications") and m.get("ts"):
                try:
                    msg_date = datetime.fromtimestamp(float(m["ts"]), tz=office_tz)
                    date_prefix = f"[POSTED {msg_date.strftime('%B %d, %Y')}] "
                    # Replace "Today's" with the actual date so AI doesn't guess
                    text = text.replace("Today's birthday", f"Birthday on {msg_date.strftime('%B %d')}")
                    text = text.replace("today's birthday", f"Birthday on {msg_date.strftime('%B %d')}")
                except (ValueError, OSError):
                    pass

            parts.append(
                f"- {date_prefix}[{m['user']}] {text}{reactions_str}{links_str}{images_str}"
            )

            # Include thread replies so AI sees full discussion context
            thread_replies = m.get("thread_replies", [])
            if thread_replies:
                parts.append(f"  THREAD REPLIES ({len(thread_replies)}):")
                for reply in thread_replies[:10]:
                    reply_text = reply.get("text", "")[:300]
                    reply_text = _resolve_mentions(reply_text, user_id_map)
                    reply_author = reply.get("user", "")
                    # Skip excluded authors in threads too
                    if reply_author.lower().strip() in EXCLUDED_AUTHORS:
                        continue
                    parts.append(f"    → [{reply_author}] {reply_text}")

    return "\n".join(parts)


def build_avatar_lookup(content):
    """Build name → avatar URL mapping from collected data."""
    raw = content.get("user_avatars", {})
    # Filter out __id__ entries (contain dicts, not strings) — keep only name→url pairs
    avatars = {k: v for k, v in raw.items() if not k.startswith("__id__") and isinstance(v, str)}
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
1. "birthday" — birthday celebrations. PRIMARY source: #birthdays channel. ANYONE can post congratulations there — not just Ira. Look for messages containing birthday-related keywords (birthday, happy birthday, congratulations, поздравляем, день рождения) with @Name mentions. The @mentions are resolved to real names. SECONDARY source: #birthdays-notifications (structured bot data). RULES:
   - Create a SEPARATE birthday slide for EACH person. NEVER combine multiple people into one slide
   - ONLY create birthday slides for people whose congratulation was POSTED TODAY or YESTERDAY (check the [POSTED date] prefix). Never show older birthdays
   - For the "date" field: just write "Happy Birthday!" — do NOT include a specific date (weekend birthdays get posted on Monday, so dates are unreliable)
   - NEVER invent names. Only use names that appear as @Name in the messages
   - For "teamNote": FIRST check the EMPLOYEE JOB TITLES section for the person's real job title from their Slack profile. If found, use it (e.g., "General Manager of Gaming", "AI Automation Specialist"). If not in the job titles list, check #birthdays-notifications data. If STILL no role info available, write a simple warm note like "Wishing you a wonderful day!" — do NOT invent or guess job titles, roles, or descriptions
   - NEVER describe what a person does unless that information is explicitly in the data. No guessing
   - Check if the birthday person replied in #birthdays — if they wrote a thank-you, include it in "message"
2. "win" — achievements, wins, metrics improvements
3. "clap" — peer recognition / kudos from #claps channel
4. "newjoin" — new team members joining
5. "event" — upcoming events / conferences
6. "milestone" — company milestones, big numbers
7. "reading" — interesting articles/links shared ONLY from #to_read channel
8. "officelife" — fun office moments, quotes, culture. DO NOT just quote messages — write a brief engaging summary or intro that explains WHY this is interesting, then include the key insight or quote
9. "celebration" — ONLY for real company rituals/events that actually happened (e.g., actual Friday drinks, actual team lunch). NEVER create generic "celebration" slides with made-up discussion questions or engagement prompts. Every slide must be grounded in REAL content from the data
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
- TARGET: Aim for AT LEAST 25 slides. Be creative and thorough — split big topics into multiple slides, create separate slides for each interesting message, add more claps, more wins, more officelife moments
- SKIP birthday slides entirely if no one has a birthday TODAY or YESTERDAY. Never show birthdays from last week or earlier
- SKIP any slide type that has no fresh content — NEVER invent fake content
- NEVER create slides with generic engagement questions, discussion prompts, or motivational filler. Every single slide must be based on REAL content from the data. If you can't point to a specific message or data source for a slide — don't create it
- Write in English, concise and punchy — displayed on big screens
- DO NOT just paste raw Slack messages as quotes. Instead, write engaging summaries and intros that explain the context and why it matters. Add editorial flair — you are a curator, not a copy machine
- CAPTURE THE FULL MESSAGE, NOT JUST THE POSITIVE OPENING. This is critical:
  * If a message has multiple themes (praise + call to action, announcement + requirement), create SEPARATE slides for each theme
  * If someone starts with praise but the core message is a policy change, requirement, or call to action — you MUST create a slide about that core message. Do NOT cherry-pick only the feel-good part
  * THREAD REPLIES are part of the story! If replies discuss security concerns, action items, or important follow-ups — include those as separate slides
  * Example: "Great progress in building tools! But we must follow security practices and use managed deployments" → create TWO slides: one about the tools innovation, one about the security/deployment requirement
  * BAD: creating only an "Innovation Mindset" slide from a message whose main point is about security practices
- Use varied emojis for different slides
- Warm, positive, engaging tone — but HONEST. Reflect the real message, not a sugar-coated version
- For "win" slides, extract specific metrics/numbers when available
- For "clap" slides, extract company values mentioned (e.g., "We work TOGETHER to SERVE OTHERS")
- For "reading", pick the 2-3 most interesting articles — ONLY from #to_read channel
- NEVER mix different things into one "reading" slide. Book Club = "event" type. Article suggestions from #to_read = "reading" type. These are SEPARATE slides
- COLOR GUIDANCE: Choose accent colors that match the theme. Spring events = green (#22C55E/#16A34A). Fire/hot topics = red/orange. Tech/DevOps = blue/purple. Growth/money = green. Celebration = gold/yellow. Use varied colors across slides — avoid repeating the same color
- Order slides for maximum engagement: start exciting, mix types, end with a call-to-action
- If a channel has multiple interesting messages, create separate slides for each
- Create at least one "officelife" or "celebration" slide to keep it warm and human
- Return ONLY the JSON array, no markdown, no explanation

CONTENT FILTER — NEVER include:
- Terminations, layoffs, firings, people leaving the company
- Demotions or role downgrades
- Negative HR actions or disciplinary matters
- Any sensitive personnel changes
- Messages by or about "Liliya Garifullina" / "Liliya" — she manages this dashboard and should not appear on slides to avoid conflict of interest. Exception: if she receives a clap from someone else, that's fine
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
YOU MUST create 2-4 slides from these meeting highlights. This is MANDATORY — do NOT skip this section.
Use "milestone", "win", or "event" type. These meetings contain real company decisions and progress — they are MORE valuable than static facts.

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
        # date can be int (Unix timestamp) or string — safely convert
        date_raw = m.get("date", "")
        if isinstance(date_raw, (int, float)):
            try:
                ts = date_raw / 1000 if date_raw > 1e12 else date_raw
                date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                date = str(date_raw)
        else:
            date = str(date_raw)[:10] if date_raw else ""
        participants = m.get("participant_count", 0)
        duration = m.get("duration_min", 0)
        overview = m.get("overview", "")
        bullets = m.get("bullets", "")
        kw_list = m.get("keywords") or []
        keywords = ", ".join(kw_list[:8]) if isinstance(kw_list, list) else str(kw_list)

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

    # Use office timezone (CET/CEST) so "today" matches the office wall clock
    office_tz = timezone(timedelta(hours=config.OFFICE_TZ_OFFSET))
    today_dt = datetime.now(office_tz)
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

    # Build job titles section from Slack profiles
    titles_section = ""
    if content and content.get("user_avatars"):
        raw_avatars = content["user_avatars"]
        titles = {k.replace("__title__", ""): v for k, v in raw_avatars.items()
                  if k.startswith("__title__") and isinstance(v, str) and v}
        if titles:
            titles_lines = json.dumps(titles, ensure_ascii=False, indent=2)
            titles_section = f"""

EMPLOYEE JOB TITLES (from Slack profiles — use for birthday slides and team context):
{titles_lines}

When creating birthday slides, use the REAL job title from this list for "teamNote". These are official titles from Slack profiles.
"""

    user_prompt = f"""Today is {today} ({day_name}).

Here are the raw Slack messages from the last {config.LOOKBACK_HOURS} hours across our channels.
PRIORITY: Focus on the freshest content first (last 24 hours). If there isn't enough for 15 slides, expand to 48 hours, then 72 hours. Always prefer newer content over older.

{channel_summary}
{avatar_section}{titles_section}"""

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
        max_tokens=8192,
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

def filter_excluded_people(slides):
    """Programmatically remove slides featuring excluded people.

    This is a hard filter — AI prompt rules alone are unreliable.
    """
    EXCLUDED_NAMES = ["liliya garifullina", "liliya", "лилия гарифуллина", "лилия"]

    def _mentions_excluded(slide):
        """Check if a slide prominently features an excluded person."""
        # Fields that indicate the slide is ABOUT this person
        feature_fields = ["name", "who", "author"]
        for field in feature_fields:
            val = slide.get(field, "")
            if isinstance(val, str) and val.lower().strip() in EXCLUDED_NAMES:
                return True

        # Check "from" field for claps — but claps FROM excluded person are OK to filter,
        # claps TO excluded person are fine to keep (exception)
        from_val = slide.get("from", "")
        if isinstance(from_val, str) and from_val.lower().strip() in EXCLUDED_NAMES:
            return True

        return False

    filtered = [s for s in slides if not _mentions_excluded(s)]
    removed = len(slides) - len(filtered)
    if removed:
        print(f"  Filtered out {removed} slide(s) featuring excluded people")
    return filtered


def validate_and_fix_slides(slides, content=None):
    """Hard programmatic validators — AI prompt rules are unreliable.

    This function catches and fixes all known AI misbehaviors:
    1. Combined birthday slides → split into individual slides
    2. Invented job descriptions in birthdays → replace with safe default
    3. Generic filler slides (engagement questions, discussion prompts) → remove
    4. Duplicate slides → remove
    """
    # Build job titles lookup from Slack profiles
    job_titles = {}
    if content and content.get("user_avatars"):
        for k, v in content["user_avatars"].items():
            if k.startswith("__title__") and isinstance(v, str) and v:
                job_titles[k.replace("__title__", "").lower()] = v

    def _get_job_title(name):
        """Get job title from Slack profile, case-insensitive."""
        if not name:
            return ""
        name_lower = name.strip().lower()
        if name_lower in job_titles:
            return job_titles[name_lower]
        # Try first+last name partial match
        for key, title in job_titles.items():
            if name_lower in key or key in name_lower:
                return title
        return ""

    fixed = []
    removed_count = 0

    for slide in slides:
        stype = slide.get("type", "")

        # ── 1. Split combined birthday slides ──
        if stype == "birthday":
            name = slide.get("name", "")
            # Detect combined names: "Anna, Mikhail & Armaan" or "A, B, C"
            if "," in name or " & " in name or " and " in name.lower():
                # Split into individual names
                raw_names = re.split(r'\s*[,&]\s*|\s+and\s+', name, flags=re.IGNORECASE)
                raw_names = [n.strip() for n in raw_names if n.strip()]
                print(f"  [Validator] Splitting combined birthday: '{name}' → {raw_names}")
                for individual_name in raw_names:
                    new_slide = slide.copy()
                    new_slide["name"] = individual_name
                    # Use real job title if available, otherwise safe default
                    title = _get_job_title(individual_name)
                    if title:
                        new_slide["teamNote"] = title
                        print(f"  [Validator] Using real job title for {individual_name}: {title}")
                    else:
                        new_slide["teamNote"] = "Wishing you a wonderful day! 🎉"
                    new_slide["message"] = "Happy Birthday from the whole team!"
                    new_slide.pop("avatar", None)  # avatar was for first person only
                    fixed.append(new_slide)
                continue  # skip original combined slide
            else:
                # Single person birthday — still clean up invented descriptions
                team_note = slide.get("teamNote", "")
                INVENTED_PHRASES = [
                    "leads our", "brings technical", "adds fresh",
                    "yoga", "brings energy", "known for",
                    "our resident", "the team's",
                ]
                if any(phrase in team_note.lower() for phrase in INVENTED_PHRASES):
                    title = _get_job_title(name)
                    if title:
                        print(f"  [Validator] Replacing invented teamNote for {name} with real title: {title}")
                        slide["teamNote"] = title
                    else:
                        print(f"  [Validator] Removing invented teamNote for {name}")
                        slide["teamNote"] = "Wishing you a wonderful day! 🎉"

        # ── 2. Remove generic filler slides ──
        if stype == "celebration":
            # Check for generic engagement questions
            prompt1 = slide.get("prompt1", "").lower()
            prompt2 = slide.get("prompt2", "").lower()
            headline = slide.get("headline", "").lower()
            FILLER_PHRASES = [
                "what's your favorite", "how do you",
                "what are you", "share your",
                "what inspires", "how can we",
                "what would you", "what's one thing",
            ]
            if any(phrase in prompt1 or phrase in prompt2 for phrase in FILLER_PHRASES):
                print(f"  [Validator] Removing filler celebration: '{slide.get('headline', '')}'")
                removed_count += 1
                continue  # skip this slide

        # ── 3. Remove slides with "performance review" topic ──
        if stype in ("officelife", "milestone", "event"):
            headline = (slide.get("headline", "") + " " + slide.get("description", "")).lower()
            if "performance review" in headline or "performance evaluation" in headline:
                print(f"  [Validator] Removing performance review slide: '{slide.get('title', '')}'")
                removed_count += 1
                continue

        fixed.append(slide)

    # ── 4. Deduplicate by title + type ──
    seen = set()
    deduped = []
    for slide in fixed:
        key = (slide.get("type", ""), slide.get("title", ""), slide.get("name", ""))
        if key in seen:
            print(f"  [Validator] Removing duplicate: {key}")
            removed_count += 1
            continue
        seen.add(key)
        deduped.append(slide)

    if removed_count:
        print(f"  [Validator] Removed {removed_count} bad slide(s)")
    if len(deduped) != len(slides):
        print(f"  [Validator] {len(slides)} → {len(deduped)} slides after validation")

    return deduped


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
    if not name or not avatar_lookup or not isinstance(name, str):
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

        # Clap — from person (AI may return "from" as list or string)
        if stype == "clap" and not slide.get("fromAvatar"):
            from_val = slide.get("from", "")
            if isinstance(from_val, list):
                from_val = from_val[0] if from_val else ""
            avatar = _find_avatar(from_val, avatar_lookup)
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

def _clean_slack_markup(text):
    """Strip Slack markup to plain readable text."""
    if not text:
        return ""
    # <@U123> mentions → remove (we don't know the name in this context)
    text = re.sub(r'<@[UW][A-Z0-9]+>', '', text)
    # <!channel>, <!here>, <!everyone> → remove
    text = re.sub(r'<!(?:channel|here|everyone)>', '', text)
    # <https://url|label> → label
    text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'\2', text)
    # <https://url> → url
    text = re.sub(r'<(https?://[^>]+)>', r'\1', text)
    # :emoji_name: → remove
    text = re.sub(r':[a-z0-9_+-]+:', '', text)
    # *bold* → bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    # _italic_ → italic
    text = re.sub(r'_([^_]+)_', r'\1', text)
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _build_user_id_map(content):
    """Build user_id → {name, avatar} mapping from content data."""
    id_map = {}
    # First: use __id__ entries from user_avatars (collected from users.list)
    for key, val in content.get("user_avatars", {}).items():
        if key.startswith("__id__") and isinstance(val, dict):
            uid = key.replace("__id__", "")
            id_map[uid] = val
    # Also scan messages for any IDs not in the workspace lookup
    for ch_data in content.get("channels", {}).values():
        for msg in ch_data.get("messages", []):
            uid = msg.get("user_id", "")
            name = msg.get("user", "")
            if uid and name and uid not in id_map:
                id_map[uid] = {"name": name, "avatar": msg.get("user_avatar", "")}
    return id_map


def generate_fallback_slides(content):
    """Generate basic slides without AI if API is unavailable."""
    slides = []
    today = datetime.now().strftime("%B %d")
    user_id_map = _build_user_id_map(content)

    # Parse birthdays from #birthdays-notifications (structured bot messages)
    # Format: "🎁 Today's birthday celebrants (N):\nName: X\nLocation: Y\nDepartment: Z\nDivision: W"
    # Only include messages from the last 36 hours
    bday_notif_msgs = content["channels"].get("birthdays-notifications", {}).get("messages", [])
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(hours=36)).timestamp()
    avatars_lookup = content.get("user_avatars", {})

    for msg in bday_notif_msgs:
        msg_ts = float(msg.get("ts", "0"))
        if msg_ts < cutoff_ts:
            continue
        text = msg.get("text", "")
        if "celebrants (0)" in text:
            continue  # No birthdays today

        # Extract all "Name: ..." entries from the message
        names = re.findall(r'Name:\s*(.+)', text)
        locations = re.findall(r'Location:\s*(.+)', text)
        departments = re.findall(r'Department:\s*(.+)', text)

        # Get the date from the message timestamp
        msg_date = datetime.fromtimestamp(msg_ts, tz=timezone.utc)
        date_str = msg_date.strftime("%B %d")

        for i, name in enumerate(names):
            name = name.strip()
            location = locations[i].strip() if i < len(locations) else ""
            department = departments[i].strip() if i < len(departments) else ""

            avatar = avatars_lookup.get(name, "")
            # Try first name match
            if not avatar:
                first = name.split()[0]
                avatar = avatars_lookup.get(first, "")

            team_note = ""
            if department and location:
                team_note = f"{department} · {location}"
            elif department:
                team_note = department

            slide = {
                "type": "birthday",
                "emoji": "🎂",
                **ACCENT_COLORS["birthday"],
                "title": "Happy Birthday!",
                "name": name,
                "date": date_str,
                "message": "Wishing you an amazing day filled with joy and celebration!",
                "teamNote": team_note or "With love, Your Appodeal Team 💜",
            }
            if avatar:
                slide["avatar"] = avatar
            slides.append(slide)

    # Fallback: if no birthdays-notifications data, try #birthdays channel
    if not slides:
        birthday_msgs = content["channels"].get("birthdays", {}).get("messages", [])
        birthday_names = {}
        for msg in birthday_msgs:
            msg_ts = float(msg.get("ts", "0"))
            if msg_ts < cutoff_ts:
                continue
            text = msg.get("text", "")
            text_lower = text.lower()
            bday_keywords = ["birthday", "happy", "поздравля", "день рождения", "congratulat"]
            if not any(kw in text_lower for kw in bday_keywords):
                continue
            mentioned_ids = re.findall(r'<@([UW][A-Z0-9]+)>', text)
            for uid in mentioned_ids:
                info = user_id_map.get(uid, {})
                name = info.get("name", "") if isinstance(info, dict) else info
                if name and name not in birthday_names:
                    avatar = info.get("avatar", "") if isinstance(info, dict) else ""
                    if not avatar:
                        avatar = avatars_lookup.get(name, "")
                    birthday_names[name] = avatar
        for name, avatar in birthday_names.items():
            slide = {
                "type": "birthday",
                "emoji": "🎂",
                **ACCENT_COLORS["birthday"],
                "title": "Happy Birthday!",
                "name": name,
                "date": today,
                "message": "Wishing you an amazing day filled with joy and celebration!",
                "teamNote": "With love, Your Appodeal Team 💜",
            }
            if avatar:
                slide["avatar"] = avatar
            slides.append(slide)

    # Check general for news — clean Slack markup
    general_msgs = content["channels"].get("general", {}).get("messages", [])
    for msg in sorted(general_msgs, key=lambda m: m.get("reaction_count", 0), reverse=True)[:3]:
        text = msg.get("text", "")
        if len(text) < 20:
            continue
        clean = _clean_slack_markup(text)
        if len(clean) < 15:
            continue
        slides.append({
            "type": "officelife",
            "emoji": "📢",
            **ACCENT_COLORS["officelife"],
            "title": "From #general",
            "headline": clean[:80] + ("..." if len(clean) > 80 else ""),
            "quote": clean[:300],
            "author": msg.get("user", ""),
            "reactions": "",
            "channel": "#general",
        })

    # Check pets
    pet_msgs = content["channels"].get("appodeal_pets", {}).get("messages", [])
    for msg in pet_msgs[:1]:
        if msg.get("images") or msg.get("text"):
            clean = _clean_slack_markup(msg.get("text", ""))
            slides.append({
                "type": "officelife",
                "emoji": "🐾",
                **ACCENT_COLORS["pet"],
                "title": "Pet of the Day",
                "headline": "Our furry friends!",
                "quote": clean[:200] if clean else "Look at this cutie!",
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
            desc = _clean_slack_markup(link.get("text", msg.get("text", "")))
            articles.append({
                "title": link.get("title", "Interesting Read"),
                "sharedBy": msg.get("user", ""),
                "desc": desc[:150],
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

    # Check claps channel
    clap_msgs = content["channels"].get("claps", {}).get("messages", [])
    for msg in clap_msgs[:2]:
        text = msg.get("text", "")
        clean = _clean_slack_markup(text)
        if len(clean) > 15:
            slides.append({
                "type": "officelife",
                "emoji": "👏",
                **ACCENT_COLORS.get("clap", ACCENT_COLORS["celebration"]),
                "title": "From #claps",
                "headline": clean[:80] + ("..." if len(clean) > 80 else ""),
                "quote": clean[:300],
                "author": msg.get("user", ""),
                "reactions": "",
                "channel": "#claps",
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
            slides = validate_and_fix_slides(slides, content)
            slides = apply_accents(slides)
            slides = inject_avatars(slides, avatar_lookup)
            slides = filter_excluded_people(slides)
            print(f"  AI generated {len(slides)} slides")
        except Exception as e:
            print(f"  AI curation failed: {e}")
            traceback.print_exc()
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
