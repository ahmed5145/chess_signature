"""
Pull your games from Chess.com and Lichess (public APIs, no login required) and
cache them locally. Run this once; it can take a while if you have a lot of games.
Re-run it later to refresh -- it only pulls Chess.com months you don't already have.

Configure your accounts below, then:  python fetch_games.py

Importable API: fetch_all(chesscom_users, lichess_users, ...) -> list[dict]
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# CONFIG -- put your own usernames here. Add as many as you want to each list.
# ---------------------------------------------------------------------------
CHESSCOM_USERS = []           # e.g. ["MyChessComName", "old_account"]
LICHESS_USERS = []            # e.g. ["MyLichessName"]

# Optional: a Lichess personal API token (https://lichess.org/account/oauth/token)
# raises your rate limit. Not required. Set LICHESS_TOKEN in your env if you have one.
LICHESS_TOKEN = os.environ.get("LICHESS_TOKEN", "").strip()

# Cap per Lichess account so a huge history doesn't take forever. Raise/remove freely.
LICHESS_MAX_GAMES = 8000

CACHE_FILE = "games_cache.json"
# Chess.com requires a descriptive User-Agent with contact info.
UA = "chess-signature/1.0 (https://github.com/ahmed5145/chess_signature; personal analytics)"
# ---------------------------------------------------------------------------


def log(msg):
    print(msg, flush=True)


def _progress(progress, msg, frac=None):
    if progress:
        progress(msg, frac)
    else:
        log(msg)


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"games": [], "chesscom_months_done": {}}


def save_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


def get(url, headers=None, stream=False, tries=5, progress=None):
    """GET with polite backoff on 429."""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    for attempt in range(tries):
        r = requests.get(url, headers=h, stream=stream, timeout=60)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "0")) or (5 * (attempt + 1))
            _progress(progress, f"    rate limited, waiting {wait}s...", None)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


# ------------------------------- Chess.com ---------------------------------
def fetch_chesscom(user, cache, progress=None, frac_base=0.0, frac_span=1.0):
    _progress(progress, f"[chess.com] {user}", frac_base)
    months_done = cache["chesscom_months_done"].setdefault(user.lower(), [])
    try:
        arch = get(
            f"https://api.chess.com/pub/player/{user}/games/archives",
            progress=progress,
        ).json()
    except requests.HTTPError as e:
        _progress(progress, f"    could not read archives for {user}: {e}", frac_base)
        return 0
    added = 0
    archives = arch.get("archives", [])
    n_arch = max(len(archives), 1)
    for i, month_url in enumerate(archives):
        key = month_url.rsplit("/player/", 1)[-1]  # user/YYYY/MM
        is_current_month = (i == len(archives) - 1)
        # skip months we already stored, except always refresh the current month
        if key in months_done and not is_current_month:
            continue
        try:
            data = get(month_url, progress=progress).json()
        except requests.HTTPError as e:
            _progress(progress, f"    skip {month_url}: {e}", None)
            continue
        # if refreshing current month, drop its old rows first
        if is_current_month and key in months_done:
            cache["games"] = [
                g for g in cache["games"]
                if not (g["platform"] == "chess.com" and g.get("_month") == key)
            ]
        for g in data.get("games", []):
            if g.get("rules") != "chess":
                continue  # skip chess960 / bughouse / etc.
            rec = normalize_chesscom(g, user, key)
            if rec:
                cache["games"].append(rec)
                added += 1
        if key not in months_done:
            months_done.append(key)
        frac = frac_base + frac_span * ((i + 1) / n_arch)
        _progress(progress, f"    {key.split('/', 1)[-1]}  (+{added} so far)", frac)
        time.sleep(0.4)  # be polite
    _progress(progress, f"    done, added {added} games", frac_base + frac_span)
    return added


def normalize_chesscom(g, account, month_key):
    white = g.get("white", {})
    black = g.get("black", {})
    user_is_white = white.get("username", "").lower() == account.lower()
    me = white if user_is_white else black
    opp = black if user_is_white else white
    result = classify_chesscom_result(me.get("result"))
    ts = g.get("end_time")
    return {
        "platform": "chess.com",
        "account": account,
        "id": g.get("url", ""),
        "_month": month_key,
        "played_at": iso(ts),
        "time_class": g.get("time_class", "unknown"),
        "color": "white" if user_is_white else "black",
        "user_rating": me.get("rating"),
        "opp_rating": opp.get("rating"),
        "result": result,
        "termination": me.get("result"),
        "pgn": g.get("pgn", ""),      # full PGN -> opening + moves parsed at render time
        "moves": "",
        "clocks": None,               # Chess.com clocks live in PGN [%clk] tags
    }


def classify_chesscom_result(r):
    if r == "win":
        return "win"
    if r in {"stalemate", "agreed", "repetition", "insufficient",
             "50move", "timevsinsufficient"}:
        return "draw"
    return "loss"  # checkmated, resigned, timeout, abandoned, lose, etc.


# -------------------------------- Lichess ----------------------------------
def fetch_lichess(user, cache, lichess_token="", lichess_max=5000,
                  progress=None, frac_base=0.0, frac_span=1.0):
    _progress(progress, f"[lichess] {user}", frac_base)
    # remove any prior rows for this account so we get a clean refresh
    cache["games"] = [
        g for g in cache["games"]
        if not (g["platform"] == "lichess" and g["account"].lower() == user.lower())
    ]
    headers = {"Accept": "application/x-ndjson"}
    token = (lichess_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = (f"https://lichess.org/api/games/user/{user}"
           f"?max={int(lichess_max)}&opening=true&moves=true"
           f"&clocks=true&evals=false&pgnInJson=false")
    added = 0
    try:
        r = get(url, headers=headers, stream=True, progress=progress)
    except requests.HTTPError as e:
        _progress(progress, f"    could not read games for {user}: {e}", frac_base)
        return 0
    for line in r.iter_lines():
        if not line:
            continue
        g = json.loads(line)
        if g.get("variant", "standard") != "standard":
            continue
        rec = normalize_lichess(g, user)
        if rec:
            cache["games"].append(rec)
            added += 1
            if added % 500 == 0:
                frac = frac_base + frac_span * min(0.95, added / max(int(lichess_max), 1))
                _progress(progress, f"    {added} games...", frac)
    _progress(progress, f"    done, added {added} games", frac_base + frac_span)
    return added


def normalize_lichess(g, account):
    players = g.get("players", {})
    wname = players.get("white", {}).get("user", {}).get("name", "")
    user_is_white = wname.lower() == account.lower()
    me = players.get("white" if user_is_white else "black", {})
    opp = players.get("black" if user_is_white else "white", {})
    winner = g.get("winner")  # "white" | "black" | None(draw)
    if winner is None:
        result = "draw"
    else:
        result = "win" if (winner == "white") == user_is_white else "loss"
    opening = g.get("opening", {})
    ts = g.get("createdAt")  # epoch millis
    # Lichess clocks are centiseconds remaining after each half-move
    raw_clocks = g.get("clocks")
    clocks = list(raw_clocks) if isinstance(raw_clocks, list) else None
    return {
        "platform": "lichess",
        "account": account,
        "id": g.get("id", ""),
        "_month": "",
        "played_at": iso(ts / 1000 if ts else None),
        "time_class": g.get("speed", "unknown"),
        "color": "white" if user_is_white else "black",
        "user_rating": me.get("rating"),
        "opp_rating": opp.get("rating"),
        "result": result,
        "termination": g.get("status"),
        "eco": opening.get("eco", ""),
        "opening": opening.get("name", ""),
        "pgn": "",
        "moves": g.get("moves", ""),   # SAN, space-separated
        "clocks": clocks,
    }


def iso(epoch_seconds):
    if not epoch_seconds:
        return None
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


def fetch_all(chesscom_users, lichess_users, lichess_token="", lichess_max=5000,
              progress=None, cache=None, after_account=None):
    """
    Fetch games for the given accounts and return the full list of game records.
    Does not write files. Pass an existing cache dict to keep Chess.com month
    incremental behavior; otherwise starts empty.
    after_account(cache), if given, is called after each account finishes
    (used by the CLI to persist games_cache.json).
    """
    if cache is None:
        cache = {"games": [], "chesscom_months_done": {}}
    else:
        cache.setdefault("games", [])
        cache.setdefault("chesscom_months_done", {})

    cc = list(chesscom_users or [])
    li = list(lichess_users or [])
    total_accounts = max(len(cc) + len(li), 1)
    done = 0

    for u in cc:
        span = 1.0 / total_accounts
        fetch_chesscom(
            u, cache, progress=progress,
            frac_base=done / total_accounts, frac_span=span,
        )
        done += 1
        if after_account:
            after_account(cache)

    for u in li:
        span = 1.0 / total_accounts
        fetch_lichess(
            u, cache,
            lichess_token=lichess_token,
            lichess_max=lichess_max,
            progress=progress,
            frac_base=done / total_accounts, frac_span=span,
        )
        done += 1
        if after_account:
            after_account(cache)

    _progress(progress, f"Fetched {len(cache['games']):,} games total", 1.0)
    return cache["games"]


# ---------------------------------- main -----------------------------------
def main():
    if not CHESSCOM_USERS and not LICHESS_USERS:
        log("Add at least one username to CHESSCOM_USERS or LICHESS_USERS at the "
            "top of this file.")
        sys.exit(1)
    cache = load_cache()

    def after_account(c):
        save_cache(c)

    games = fetch_all(
        CHESSCOM_USERS,
        LICHESS_USERS,
        lichess_token=LICHESS_TOKEN,
        lichess_max=LICHESS_MAX_GAMES,
        progress=lambda msg, frac: log(msg),
        cache=cache,
        after_account=after_account,
    )
    log(f"\nCache now holds {len(games)} games -> {CACHE_FILE}")
    log("Next: python make_signature.py")


if __name__ == "__main__":
    main()
