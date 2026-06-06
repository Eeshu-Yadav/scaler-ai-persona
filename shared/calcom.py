"""Cal.com v2 API client — availability lookup + real booking creation.

Used by both the Django chat backend and the LiveKit voice agent so booking
logic exists exactly once. Requires:
  CALCOM_API_KEY        cal_live_... (Settings → Developer → API Keys)
  CALCOM_EVENT_TYPE_ID  numeric id of the "Interview" event type
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

BASE = "https://api.cal.com/v2"
DEFAULT_TZ = "Asia/Kolkata"


def _headers(api_version: str) -> dict:
    return {
        "Authorization": f"Bearer {os.environ['CALCOM_API_KEY']}",
        "cal-api-version": api_version,
        "Content-Type": "application/json",
    }


def _event_type_id() -> int:
    return int(os.environ["CALCOM_EVENT_TYPE_ID"])


def get_available_slots(days_ahead: int = 7, timezone_name: str = DEFAULT_TZ) -> list[str]:
    """Return ISO start times of open slots for the next `days_ahead` days."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)
    resp = requests.get(
        f"{BASE}/slots",
        headers=_headers("2024-09-04"),
        params={
            "eventTypeId": _event_type_id(),
            "start": now.isoformat(),
            "end": end.isoformat(),
            "timeZone": timezone_name,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    slots = []
    for _day, day_slots in sorted(data.items()):
        for s in day_slots:
            slots.append(s["start"] if isinstance(s, dict) else s)
    return slots


def format_slots_human(slots: list[str], timezone_name: str = DEFAULT_TZ, limit: int = 8) -> str:
    """Condense slot list for an LLM/voice context: '<n> options: Mon Jun 8 10:00 AM IST, ...'"""
    tz = ZoneInfo(timezone_name)
    out = []
    for iso in slots[:limit]:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)
        out.append(dt.strftime("%a %b %d, %I:%M %p"))
    suffix = f" (+{len(slots) - limit} more)" if len(slots) > limit else ""
    return f"{len(slots)} open slots ({timezone_name}): " + "; ".join(out) + suffix


def create_booking(
    start_iso: str,
    attendee_name: str,
    attendee_email: str,
    timezone_name: str = DEFAULT_TZ,
    notes: str = "",
) -> dict:
    """Create a confirmed booking. Returns {success, start, meeting_url?, error?}."""
    payload = {
        "start": start_iso,
        "eventTypeId": _event_type_id(),
        "attendee": {
            "name": attendee_name,
            "email": attendee_email,
            "timeZone": timezone_name,
            "language": "en",
        },
    }
    if notes:
        payload["metadata"] = {"notes": notes[:500]}
    resp = requests.post(
        f"{BASE}/bookings", headers=_headers("2024-08-13"), json=payload, timeout=20
    )
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {}).get("message", resp.text[:300])
        except Exception:
            err = resp.text[:300]
        return {"success": False, "error": str(err)}
    data = resp.json().get("data", {})
    return {
        "success": True,
        "uid": data.get("uid"),
        "start": data.get("start", start_iso),
        "meeting_url": data.get("meetingUrl")
        or (data.get("location") if isinstance(data.get("location"), str) else None),
        "title": data.get("title"),
    }
