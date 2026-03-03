#!/usr/bin/env python3
"""
Appodeal Pulse — Web Server for Render

Serves the generated slideshow HTML.
Regenerates content on /api/refresh or via daily schedule.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler

import config


class PulseHandler(SimpleHTTPRequestHandler):
    """Serve files from output/ directory, with refresh endpoint."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=config.OUTPUT_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/api/refresh":
            self.handle_refresh()
        elif self.path == "/api/status":
            self.handle_status()
        elif self.path == "/api/health":
            self.send_json({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})
        else:
            super().do_GET()

    def handle_refresh(self):
        """Trigger content refresh."""
        try:
            regenerate()
            self.send_json({"status": "ok", "message": "Content refreshed"})
        except Exception as e:
            self.send_json({"status": "error", "message": str(e)}, code=500)

    def handle_status(self):
        """Show current content status."""
        slides_path = os.path.join(config.DATA_DIR, "slides.json")
        content_path = os.path.join(config.DATA_DIR, "content.json")
        info = {
            "slides_exist": os.path.exists(slides_path),
            "content_exist": os.path.exists(content_path),
            "output_exist": os.path.exists(os.path.join(config.OUTPUT_DIR, "index.html")),
        }
        if os.path.exists(slides_path):
            with open(slides_path, "r") as f:
                slides = json.load(f)
            info["slide_count"] = len(slides)
        if os.path.exists(content_path):
            with open(content_path, "r") as f:
                content = json.load(f)
            info["collected_at"] = content.get("collected_at", "unknown")
            info["channels"] = {
                k: v["message_count"]
                for k, v in content.get("channels", {}).items()
            }
        self.send_json(info)

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        # Quieter logging
        if "/api/" in (args[0] if args else ""):
            print(f"  API: {args[0]}")


def regenerate():
    """Run the full collect → generate pipeline."""
    print(f"\n{'='*50}")
    print(f"  Regenerating at {datetime.now()}")
    print(f"{'='*50}")

    # Collect from Slack
    if config.SLACK_BOT_TOKEN:
        import collect
        content = collect.collect_all()
        collect.save_content(content)
    else:
        print("  SLACK_BOT_TOKEN not set — skipping collection")

    # Generate slides
    import generate
    content = generate.load_content()
    summary = generate.summarize_channels(content)

    if config.ANTHROPIC_API_KEY:
        try:
            slides = generate.curate_with_ai(summary)
            slides = generate.apply_accents(slides)
        except Exception as e:
            print(f"  AI failed: {e}, using fallback")
            slides = generate.generate_fallback_slides(content)
    else:
        slides = generate.generate_fallback_slides(content)

    # Save
    slides_path = os.path.join(config.DATA_DIR, "slides.json")
    with open(slides_path, "w", encoding="utf-8") as f:
        json.dump(slides, f, ensure_ascii=False, indent=2)

    generate.generate_html(slides)
    print(f"  Done! {len(slides)} slides generated")


def daily_scheduler():
    """Background thread: regenerate content at 7:00 UTC daily."""
    while True:
        now = datetime.now(timezone.utc)
        # Next run at 7:00 UTC (9:00 CET)
        target_hour = 7
        if now.hour >= target_hour:
            # Already past — schedule for tomorrow
            seconds_until = (24 - now.hour + target_hour) * 3600 - now.minute * 60
        else:
            seconds_until = (target_hour - now.hour) * 3600 - now.minute * 60

        print(f"  Scheduler: next refresh in {seconds_until // 3600}h {(seconds_until % 3600) // 60}m")
        time.sleep(seconds_until)

        try:
            regenerate()
        except Exception as e:
            print(f"  Scheduler error: {e}")


def ensure_output():
    """Make sure output/index.html exists on startup."""
    output_html = os.path.join(config.OUTPUT_DIR, "index.html")
    if os.path.exists(output_html):
        print(f"  Serving existing {output_html}")
        return

    # Generate from existing slides if available
    slides_path = os.path.join(config.DATA_DIR, "slides.json")
    if os.path.exists(slides_path):
        print("  Building output from existing slides...")
        import generate
        with open(slides_path, "r") as f:
            slides = json.load(f)
        generate.generate_html(slides)
    else:
        # Create minimal placeholder
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        with open(output_html, "w") as f:
            f.write("<html><body style='background:#08080c;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif'><h1>Appodeal Pulse — Starting up... Hit /api/refresh</h1></body></html>")
        print("  Created placeholder. Call /api/refresh to generate content.")


if __name__ == "__main__":
    # Ensure output exists
    ensure_output()

    # Start daily scheduler in background
    scheduler = threading.Thread(target=daily_scheduler, daemon=True)
    scheduler.start()

    # Start web server
    print(f"\n  Appodeal Pulse server starting on port {config.PORT}")
    print(f"  Open: http://localhost:{config.PORT}")
    print(f"  Refresh: http://localhost:{config.PORT}/api/refresh")
    print(f"  Status: http://localhost:{config.PORT}/api/status\n")

    server = HTTPServer(("0.0.0.0", config.PORT), PulseHandler)
    server.serve_forever()
