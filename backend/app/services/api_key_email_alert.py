
"""Send API key and quota alerts through Node.js Nodemailer."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NODE_EMAIL_SCRIPT = PROJECT_ROOT / "send_api_key_issue_email.cjs"

_sent_alerts: set[str] = set()
_alert_lock = threading.Lock()


def send_api_key_issue_email(
    message: str,
    dedupe_key: str | None = None,
) -> bool:
    """Send a warning through Nodemailer without interrupting crawling."""

    if not NODE_EMAIL_SCRIPT.is_file():
        print("[api-key-alert] Nodemailer script was not found.")
        return False

    # Send at most one notification for each crawl/job ID.
    if dedupe_key:
        with _alert_lock:
            if dedupe_key in _sent_alerts:
                return True
            _sent_alerts.add(dedupe_key)

    try:
        result = subprocess.run(
            ["node", str(NODE_EMAIL_SCRIPT), message],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if result.returncode == 0:
            print("[api-key-alert] Nodemailer email sent.")
            return True

        print(
            "[api-key-alert] Email failed:",
            result.stderr.strip() or "Node.js returned an error.",
        )
        return False

    except subprocess.TimeoutExpired:
        print("[api-key-alert] Email sending timed out.")
        return False

    except Exception as exc:
        print(
            f"[api-key-alert] Email error: {type(exc).__name__}: {exc}"
        )
        return False
