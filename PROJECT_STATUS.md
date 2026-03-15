# Appodeal Pulse — Project Status

## Last Updated: 2026-03-13

## What Was Done (latest session — 2026-03-13)
- **Programmatic Liliya exclusion**: Added `EXCLUDED_AUTHORS` pre-filter + `filter_excluded_people()` post-filter (AI prompt alone was unreliable)
- **@mention resolution**: `_resolve_mentions()` converts `<@USERID>` to `@RealName` before AI processes messages
- **Birthday fixes**: Both Artem Orlov and Kirill Khramkov now appear correctly
- **Birthday dates removed**: Using "Happy Birthday!" instead of specific dates (unreliable due to weekend shifts)
- **Weekday-only schedule**: Cron changed to `0 6 * * 1-5` — no weekend updates, Friday slides stay until Monday
- **Monday extended lookback**: 80h instead of 72h to capture Saturday content
- **Color guidance**: Added thematic color rules in prompt (spring=green, tech=blue, etc.)

## Previous work
- Slack profile pictures + avatar integration in slides
- Holographic design with Appodeal-style gradients
- Large fonts for TV readability
- Content filter (blocks sensitive topics)
- PPTX archive daily
- GitHub Actions + GitHub Pages deployment

## What's Next
- Google Slides export (plan ready, waiting for GCP access)
- Confluence integration (parked)
- Slack image downloading for slides (private URLs need auth)
- TV kiosk mode optimization

## Technical Notes
- AI generates 15-20 slides per run with Claude Sonnet
- PPTX archive saved to data/archive/ daily
- Workflow runs weekdays at 6:00 UTC (8:00 CET)
- Monday lookback: 80h, other days: 72h
- GitHub Pages URL: https://liliyagarifullina-maker.github.io/appodeal-pulse/
- Password: Pulse!App0deal#2026
