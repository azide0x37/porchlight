"""Bounded, read-only Spotify presentation data; a track is never a Jam invitation."""
from __future__ import annotations

import math
import re
from datetime import datetime
from urllib.parse import urlsplit

PLAYER = re.compile(r"^media_player\.[a-z0-9_]{1,100}$")
FIELDS = {"id", "state", "title", "artist", "album", "source", "duration", "position"}


def validate_spotify(value, allowed):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("invalid_spotify_fields")
    if not isinstance(value["id"], str) or value["id"] not in allowed:
        raise ValueError("unapproved_spotify")
    if value["state"] not in ("playing", "paused"):
        raise ValueError("invalid_spotify_state")
    for field in ("title", "artist", "album", "source"):
        item = value[field]
        if item is not None and (not isinstance(item, str) or len(item) > 256 or any(ord(c) < 32 for c in item)):
            raise ValueError("invalid_spotify_text")
    if not value["title"]:
        raise ValueError("spotify_title_required")
    for field in ("duration", "position"):
        item = value[field]
        if item is not None and (type(item) not in (int, float) or not 0 <= item <= 86400 or not math.isfinite(item)):
            raise ValueError("invalid_spotify_number")
    return value


def validate_jam(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"url", "session_id", "expires_at"}:
        raise ValueError("invalid_spotify_jam")
    if not isinstance(value["url"], str) or len(value["url"]) > 255:
        raise ValueError("invalid_spotify_jam")
    url = urlsplit(value["url"])
    if (url.scheme != "https" or url.username or url.password or url.port or url.query or url.fragment
            or not ((url.hostname == "spotify.link" and re.fullmatch(r"/[A-Za-z0-9_-]{6,160}", url.path))
                    or (url.hostname == "open.spotify.com" and re.fullmatch(r"/jam/[A-Za-z0-9_-]{6,160}", url.path)))):
        raise ValueError("invalid_spotify_jam")
    if not isinstance(value["session_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,100}", value["session_id"]):
        raise ValueError("invalid_spotify_jam_session")
    try:
        stamp = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("timezone_required")
        stamp.timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid_spotify_jam_expiry") from exc
    return value


def jam_for_session(value, session, now):
    """No automatic Jam detection: only show the host's invite for this session, <=4h."""
    if value and value["session_id"] == session:
        expiry = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00")).timestamp()
        if 0 < expiry - now <= 4 * 3600:
            return {"url": value["url"], "expires_at": value["expires_at"]}
    return None
