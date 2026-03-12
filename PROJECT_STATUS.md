# Appodeal Pulse — Project Status

## Last Updated: 2026-03-12

## What Was Done
- **Slack profile pictures**: collect.py now fetches user avatar URLs (image_192) from Slack API
- **Avatar integration**: generate.py passes avatar lookup to Claude AI and injects avatars into slides post-processing
- **Holographic design**: index.html rewritten with Appodeal-style holographic gradients, animated glow effects
- **~2x larger fonts**: All text scaled up for TV readability (titles 52px, body 22px, stats 72-80px)
- **Avatar component**: React Avatar component shows Slack profile pics or colored initials fallback
- **Avatars in slides**: Birthday, Win, Clap, NewJoin, OfficeLife slides display user photos
- **Birthday rule**: Only shows birthday slides if someone has birthday TODAY or YESTERDAY
- **Content filter**: Blocks termination/layoff/demotion messages in both collect.py and AI prompt
- **PPTX fix**: Fixed TypeError when slide data contains non-string values
- **Deployed**: GitHub Actions workflow running, GitHub Pages live

## What's Next
- Confluence integration (parked, user asked about it)
- Real-time Fireflies API (currently hardcoded strategic data)
- Add more Slack channels if user wants
- TV kiosk mode optimization

## Technical Notes
- 23 user avatars collected from current Slack workspace
- AI generates 15-20 slides per run with Claude Sonnet
- PPTX archive saved to data/archive/ daily
- Workflow runs daily at 6:00 UTC (8:00 CET)
- GitHub Pages URL: https://liliyagarifullina-maker.github.io/appodeal-pulse/
- Password: Pulse!App0deal#2026
