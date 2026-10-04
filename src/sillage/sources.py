from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen


GITHUB_STATUS_URL = "https://www.githubstatus.com/api/v2/summary.json"


def github_status_snapshot(timeout_seconds: float = 4.0) -> dict[str, object]:
    request = Request(GITHUB_STATUS_URL, headers={"User-Agent": "sillage-ai-demo/0.1"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        status = payload.get("status", {})
        return {
            "source": "github_status",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "ok": True,
            "indicator": status.get("indicator", "unknown"),
            "description": status.get("description", "No description returned."),
            "source_url": GITHUB_STATUS_URL,
        }
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return {
            "source": "github_status",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "indicator": "unavailable",
            "description": "La source publique n'a pas répondu. Le triage local reste disponible.",
            "source_url": GITHUB_STATUS_URL,
            "error": type(error).__name__,
        }
