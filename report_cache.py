"""
Server-side report cache (disk + optional Streamlit memory layer).

Caches fetched games and rendered HTML by username set so repeat visitors
(and other sessions on the same host) skip Chess.com/Lichess fetches and the
board walk. Entries expire after TTL and the directory is capped by count.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import pickle
import time
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "reports"
TTL_SECONDS = 6 * 60 * 60  # 6 hours
MAX_ENTRIES = 40


def cache_id(chesscom, lichess, token: str, max_games: int) -> str:
    payload = {
        "chesscom": sorted(u.lower() for u in chesscom),
        "lichess": sorted(u.lower() for u in lichess),
        # Hash token so the raw secret never appears in filenames.
        "token_fp": hashlib.sha256((token or "").encode("utf-8")).hexdigest()[:16],
        "max_games": int(max_games),
        "v": 1,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _path_for(cid: str) -> Path:
    return CACHE_DIR / f"{cid}.pkl.gz"


def load_report(cid: str):
    """Return cached dict or None if missing/expired/corrupt."""
    path = _path_for(cid)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > TTL_SECONDS:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    try:
        with gzip.open(path, "rb") as f:
            data = pickle.load(f)
        if not isinstance(data, dict) or "games" not in data or "html" not in data:
            return None
        if not data.get("games"):
            return None
        return data
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def save_report(cid: str, data: dict) -> None:
    """Persist a successful report. Skips empty game lists."""
    if not data or not data.get("games"):
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(cid)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)
    _prune()


def _prune() -> None:
    if not CACHE_DIR.exists():
        return
    files = sorted(
        CACHE_DIR.glob("*.pkl.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[MAX_ENTRIES:]:
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass


def clear_report(cid: str) -> None:
    try:
        _path_for(cid).unlink(missing_ok=True)
    except OSError:
        pass
