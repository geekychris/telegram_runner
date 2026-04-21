"""Minimal standalone CLI for sending Telegram messages.

Installed as `tg-send` — a lightweight tool for use in shell scripts,
cron jobs, CI/CD pipelines, and other automation.

Usage:
    tg-send "Build complete"
    echo "Error on line 42" | tg-send -
    tg-send -t 123456789 "Alert: disk at 95%"
    deploy.sh && tg-send "Deploy succeeded" || tg-send "Deploy FAILED"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _resolve_token() -> str:
    """Find bot token from env var or config file."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        return token

    # Try config file
    for config_path in ["telegram_harness.json", os.path.expanduser("~/.telegram_harness.json")]:
        p = Path(config_path)
        if p.exists():
            try:
                cfg = json.loads(p.read_text())
                t = cfg.get("telegram", {}).get("bot_token", "")
                if t and not t.startswith("${"):
                    return t
            except Exception:
                pass

    return ""


def _resolve_chat_id(explicit: str | None) -> str:
    """Find chat ID from arg, env var, or config file."""
    if explicit:
        return explicit

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if chat_id:
        return chat_id

    # Try config file
    for config_path in ["telegram_harness.json", os.path.expanduser("~/.telegram_harness.json")]:
        p = Path(config_path)
        if p.exists():
            try:
                cfg = json.loads(p.read_text())
                ids = cfg.get("telegram", {}).get("allowed_chat_ids", [])
                if ids:
                    return str(ids[0])
            except Exception:
                pass

    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a message to Telegram. Use - to read from stdin.",
        epilog="Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or use a config file.",
    )
    parser.add_argument("message", nargs="?", default="-", help='Message text, or - for stdin (default: -)')
    parser.add_argument("-t", "--chat", help="Chat ID (default: TELEGRAM_CHAT_ID or config)")
    parser.add_argument("-s", "--silent", action="store_true", help="No output on success")
    parser.add_argument("-c", "--config", help="Config file path")
    args = parser.parse_args()

    token = _resolve_token()
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not set.", file=sys.stderr)
        print("  export TELEGRAM_BOT_TOKEN=your-token", file=sys.stderr)
        sys.exit(1)

    chat_id = _resolve_chat_id(args.chat)
    if not chat_id:
        print("Error: No chat ID. Set TELEGRAM_CHAT_ID or use --chat.", file=sys.stderr)
        sys.exit(1)

    # Read message
    if args.message == "-":
        message = sys.stdin.read()
    else:
        message = args.message

    if not message.strip():
        print("Error: Empty message.", file=sys.stderr)
        sys.exit(1)

    # Send — use urllib to avoid requiring httpx for the lightweight script
    import urllib.request
    import urllib.error

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                if not args.silent:
                    print(f"Sent to {chat_id}")
            else:
                print(f"Failed: {data.get('description', 'unknown error')}", file=sys.stderr)
                sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            desc = json.loads(body).get("description", body)
        except Exception:
            desc = body
        print(f"Failed: {desc}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
