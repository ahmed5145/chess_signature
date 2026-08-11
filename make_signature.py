"""
Turn games_cache.json into one self-contained HTML page: your chess "signature".
Run fetch_games.py first, then:  python make_signature.py
Opens/writes chess_signature.html -- just double-click it.
"""

import io
import json
import math
import os
import re
from collections import Counter
from datetime import date

import chess
import chess.pgn
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

CACHE_FILE = "games_cache.json"
OUT_FILE = "chess_signature.html"

BG = "#0b0d11"
PANEL = "#13161d"
GOLD = "#b07d2e"
INK = "#e6e6e6"
MUTED = "#8b93a7"
GREEN = "#4a9d5b"
RED = "#c0504d"
GREY = "#5b6172"

pio.templates.default = "plotly_dark"

CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")
FILES = list("abcdefgh")
PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}
PROMO_NAMES = {
    chess.QUEEN: "queen",
    chess.ROOK: "rook",
    chess.BISHOP: "bishop",
    chess.KNIGHT: "knight",
}

FAST_CLASSES = {"bullet", "blitz", "ultrabullet"}
SLOW_CLASSES = {"rapid", "classical", "correspondence"}
CHECKMATE_TERMS = {
    "checkmated", "mate", "matein1", "matein2", "matein3",
}

# GM archetype vectors: aggression, tactics, decisiveness, classical (0-100)
GM_PROFILES = [
    {"name": "Mikhail Tal", "vec": (95, 98, 88, 35),
     "openings": ["Sicilian Defense", "King's Gambit", "Modern Defense"]},
    {"name": "Garry Kasparov", "vec": (92, 90, 85, 40),
     "openings": ["Sicilian Defense", "King's Indian Defense", "Nimzo-Indian Defense"]},
    {"name": "Bobby Fischer", "vec": (88, 85, 90, 55),
     "openings": ["Sicilian Defense", "Ruy Lopez", "King's Indian Defense"]},
    {"name": "Paul Morphy", "vec": (90, 95, 92, 70),
     "openings": ["King's Gambit", "Italian Game", "Evans Gambit"]},
    {"name": "Magnus Carlsen", "vec": (55, 60, 70, 65),
     "openings": ["Queen's Pawn Opening", "London System", "Ruy Lopez", "Italian Game"]},
    {"name": "Anatoly Karpov", "vec": (35, 40, 55, 75),
     "openings": ["Caro-Kann Defense", "Queen's Gambit Declined", "Ruy Lopez"]},
    {"name": "Tigran Petrosian", "vec": (25, 35, 45, 70),
     "openings": ["Caro-Kann Defense", "French Defense", "Queen's Indian Defense"]},
    {"name": "Jose Capablanca", "vec": (40, 45, 50, 80),
     "openings": ["Queen's Gambit Declined", "Ruy Lopez", "Orthodox Defense"]},
    {"name": "Aron Nimzowitsch", "vec": (45, 50, 55, 20),
     "openings": ["Nimzo-Indian Defense", "French Defense", "English Opening"]},
    {"name": "Viswanathan Anand", "vec": (70, 75, 80, 50),
     "openings": ["Sicilian Defense", "Ruy Lopez", "Semi-Slav Defense"]},
]

OPENING_GM_BUMPS = [
    (["najdorf", "sicilian"], ["Bobby Fischer", "Garry Kasparov"], 12),
    (["king's indian", "kings indian"], ["Garry Kasparov", "Bobby Fischer"], 10),
    (["caro-kann", "caro kann", "french"], ["Tigran Petrosian", "Anatoly Karpov"], 12),
    (["london", "queen's pawn", "queens pawn"], ["Magnus Carlsen"], 10),
    (["englund", "king's gambit", "kings gambit", "evans"], ["Paul Morphy", "Mikhail Tal"], 14),
    (["nimzo", "larsen", "reti", "réti"], ["Aron Nimzowitsch"], 12),
]

ARCHETYPE_NAMES = {
    "AT": "The Sacrificer",
    "AS": "The Strangler",
    "AP": "The Blitz Bandit",
    "AM": "The Long Knife",
    "AX": "The Tourist Assassin",
    "AZ": "The Sharpshooter",
    "DT": "The Counterpuncher",
    "DS": "The Grinder",
    "DP": "The Sandbag Sprinter",
    "DM": "The Fortress",
    "DX": "The Shape-Shifter",
    "DZ": "The Iron Specialist",
    "TP": "The Tactic Sprinter",
    "TM": "The Slow Trapper",
    "TX": "The Puzzle Hunter",
    "TZ": "The Sniper",
    "SP": "The Rapid Architect",
    "SM": "The Squeeze",
    "SX": "The Opening Nomad",
    "SZ": "The One-Line Boss",
    "PX": "The Speed Explorer",
    "PZ": "The Pocket Repertoire",
    "MX": "The Marathon Scout",
    "MZ": "The Deep Specialist",
    "AD": "The Balanced Blade",
    "TS": "The Mixed Calculator",
    "PM": "The Tempo Mixer",
    "XZ": "The Curious Specialist",
}


# --------------------------- load + parse ----------------------------------
def load_games():
    if not os.path.exists(CACHE_FILE):
        raise SystemExit("No games_cache.json found. Run fetch_games.py first.")
    with open(CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)["games"]


def clean_opening(name):
    if not name:
        return "Unknown"
    return name.split(":")[0].split(",")[0].strip() or "Unknown"


def family_from_eco_url(eco_url):
    """Turn Chess.com ECOUrl slug into an opening family name."""
    if not eco_url:
        return ""
    slug = eco_url.rstrip("/").rsplit("/", 1)[-1]
    parts = slug.split("-")
    stop = {"Defense", "Opening", "Game", "Attack", "Gambit", "System"}
    out = []
    for p in parts:
        if not p or p.startswith("...") or p[0].isdigit():
            break
        out.append(p)
        if p in stop:
            break
    return " ".join(out) if out else slug.replace("-", " ")


def parse_clk_seconds(comment):
    if not comment:
        return None
    m = CLK_RE.search(comment)
    if not m:
        return None
    h, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mm * 60 + ss


def empty_walk_stats():
    return {
        "user_moves": 0,
        "user_captures": 0,
        "user_checks": 0,
        "pieces_lost": 0,
        "castle_king": 0,
        "castle_queen": 0,
        "promotions": Counter(),
        "en_passant": 0,
        "piece_moved": Counter(),
        "square_landed": Counter(),
        "mates_by_piece": Counter(),
        "mates_delivered": 0,
        "early_queen_games": 0,
        "games_walked": 0,
        "opp_castle_games": 0,
        "opp_castle_opposite": 0,
        "scramble_games": 0,
        "scramble_wins": 0,
        "has_any_clock": False,
        "captures_per_game": [],
        "first_moves_white": Counter(),
        "longest_game_moves": 0,
        "fastest_mate_win_moves": None,
    }


def extract_game_data(rec):
    """Return (sans, eco, opening, clocks_in_seconds_or_None, pgn_termination)."""
    if rec.get("pgn"):
        game = chess.pgn.read_game(io.StringIO(rec["pgn"]))
        if game is None:
            return [], rec.get("eco", ""), rec.get("opening", ""), None, ""
        eco = game.headers.get("ECO", rec.get("eco", ""))
        opening = game.headers.get("Opening", "") or rec.get("opening", "")
        if not opening:
            opening = family_from_eco_url(game.headers.get("ECOUrl", ""))
        pgn_term = game.headers.get("Termination", "")
        sans = []
        clocks = []
        node = game
        while node.variations:
            node = node.variation(0)
            sans.append(node.san())
            clocks.append(parse_clk_seconds(node.comment))
        if not any(c is not None for c in clocks):
            clocks = None
        return sans, eco, opening, clocks, pgn_term

    moves_str = rec.get("moves", "")
    sans = moves_str.split() if moves_str else []
    raw = rec.get("clocks")
    clocks = None
    if isinstance(raw, list) and raw and sans:
        clocks = [c / 100.0 if c is not None else None for c in raw[:len(sans)]]
    return sans, rec.get("eco", ""), rec.get("opening", ""), clocks, ""


def walk_game(sans, user_is_white, clocks_sec, activity, captures_taken, stats,
              termination, result):
    """Single board walk: heatmaps + every fun / personality counter."""
    board = chess.Board()
    user_caps = 0
    user_castled = None
    opp_castled = None
    early_queen = False
    user_scrambled = False
    last_user_piece = None
    ply = 0

    for i, san in enumerate(sans):
        try:
            move = board.parse_san(san)
        except Exception:
            break
        mover_is_white = board.turn == chess.WHITE
        is_user = mover_is_white == user_is_white
        piece = board.piece_at(move.from_square)
        is_capture = board.is_capture(move)
        is_ep = board.is_en_passant(move)
        gives_check = board.gives_check(move)
        is_castle = board.is_castling(move)
        target = move.to_square
        fullmove = board.fullmove_number

        if is_user:
            stats["user_moves"] += 1
            if piece:
                pname = PIECE_NAMES[piece.piece_type]
                stats["piece_moved"][pname] += 1
                last_user_piece = pname
                if piece.piece_type == chess.QUEEN and fullmove <= 8 and not early_queen:
                    early_queen = True
            user_sq = target if user_is_white else chess.square_mirror(target)
            activity[chess.square_rank(user_sq)][chess.square_file(user_sq)] += 1
            stats["square_landed"][chess.square_name(user_sq)] += 1
            if is_capture:
                user_caps += 1
                stats["user_captures"] += 1
            if is_ep:
                stats["en_passant"] += 1
            if gives_check:
                stats["user_checks"] += 1
            if is_castle:
                side = "Q" if chess.square_file(target) == 2 else "K"
                user_castled = side
                if side == "Q":
                    stats["castle_queen"] += 1
                else:
                    stats["castle_king"] += 1
            if move.promotion:
                stats["promotions"][PROMO_NAMES.get(move.promotion, "other")] += 1
        else:
            if is_capture:
                user_sq = target if user_is_white else chess.square_mirror(target)
                captures_taken[chess.square_rank(user_sq)][chess.square_file(user_sq)] += 1
                stats["pieces_lost"] += 1
            if is_castle:
                opp_castled = "Q" if chess.square_file(target) == 2 else "K"

        board.push(move)
        ply += 1

        if clocks_sec is not None and i < len(clocks_sec) and clocks_sec[i] is not None:
            stats["has_any_clock"] = True
            if is_user and clocks_sec[i] < 20:
                user_scrambled = True

    stats["games_walked"] += 1
    stats["captures_per_game"].append(user_caps)
    if early_queen:
        stats["early_queen_games"] += 1
    if user_castled and opp_castled:
        stats["opp_castle_games"] += 1
        if user_castled != opp_castled:
            stats["opp_castle_opposite"] += 1
    if user_scrambled:
        stats["scramble_games"] += 1
        if result == "win":
            stats["scramble_wins"] += 1

    if ply > stats["longest_game_moves"]:
        stats["longest_game_moves"] = ply

    term = str(termination or "").lower()
    is_mate_term = term in CHECKMATE_TERMS
    if result == "win" and (board.is_checkmate() or is_mate_term):
        stats["mates_delivered"] += 1
        if last_user_piece:
            stats["mates_by_piece"][last_user_piece] += 1
        mate_moves = (ply + 1) // 2
        prev = stats["fastest_mate_win_moves"]
        if prev is None or mate_moves < prev:
            stats["fastest_mate_win_moves"] = mate_moves

    return ply


def build_frame(games):
    rows = []
    activity = np.zeros((8, 8))
    captures_taken = np.zeros((8, 8))
    stats = empty_walk_stats()

    for idx, rec in enumerate(games):
        if idx and idx % 2000 == 0:
            print(f"  ...{idx:,}/{len(games):,}")
        sans, eco, opening, clocks, pgn_term = extract_game_data(rec)
        opening = clean_opening(opening)
        user_is_white = rec.get("color") == "white"
        term = str(rec.get("termination") or "").lower()
        # Chess.com stores winner termination as "win"; mate lives in PGN header
        mate_signal = (
            term in CHECKMATE_TERMS
            or "checkmate" in str(pgn_term).lower()
            or term == "mate"
        )
        ended_mate = bool(mate_signal and rec.get("result") == "win")
        n_moves = walk_game(
            sans, user_is_white, clocks, activity, captures_taken, stats,
            "mate" if ended_mate else rec.get("termination"), rec.get("result"),
        )
        if user_is_white and sans:
            first = sans[0].replace("+", "").replace("#", "")
            if first in {"e4", "d4", "Nf3", "c4"}:
                stats["first_moves_white"][first] += 1
            else:
                stats["first_moves_white"]["other"] += 1

        rec2 = dict(rec)
        rec2["eco"] = eco
        rec2["opening"] = opening
        rec2["n_moves"] = n_moves if n_moves else len(sans)
        rec2["ended_mate"] = ended_mate
        rows.append(rec2)

    df = pd.DataFrame(rows)
    df["played_at"] = pd.to_datetime(df["played_at"], utc=True, errors="coerce")
    df["user_rating"] = pd.to_numeric(df["user_rating"], errors="coerce")
    return df, activity, captures_taken, stats


# ------------------------ personality + GM match ---------------------------
def clamp01(x):
    return max(0.0, min(1.0, float(x)))


def pct(n, d):
    return (n / d * 100.0) if d else 0.0


def shannon_entropy(counts):
    total = sum(counts)
    if total <= 0:
        return 0.0
    ent = 0.0
    for c in counts:
        if c <= 0:
            continue
        p = c / total
        ent -= p * math.log2(p)
    return ent


def compute_axes(df, stats):
    n = len(df)
    um = max(stats["user_moves"], 1)
    capture_rate = stats["user_captures"] / um
    check_rate = stats["user_checks"] / um
    castle_total = stats["castle_king"] + stats["castle_queen"]
    qs_share = (stats["castle_queen"] / castle_total) if castle_total else 0.0
    opp_share = (stats["opp_castle_opposite"] / stats["opp_castle_games"]
                 if stats["opp_castle_games"] else 0.0)
    early_q = stats["early_queen_games"] / max(stats["games_walked"], 1)

    aggression = 100 * (
        0.28 * clamp01(capture_rate / 0.22)
        + 0.22 * clamp01(check_rate / 0.18)
        + 0.18 * clamp01(qs_share / 0.35)
        + 0.16 * clamp01(opp_share / 0.40)
        + 0.16 * clamp01(early_q / 0.25)
    )

    wins = df[df["result"] == "win"]
    mate_share = float(wins["ended_mate"].mean()) if len(wins) else 0.0
    if len(wins) and stats["mates_delivered"]:
        mate_share = max(mate_share, stats["mates_delivered"] / len(wins))
    avg_caps = (float(np.mean(stats["captures_per_game"]))
                if stats["captures_per_game"] else 0.0)
    tactics = 100 * (
        0.55 * clamp01(mate_share / 0.35)
        + 0.45 * clamp01(avg_caps / 8.0)
    )

    tc = df["time_class"].astype(str).str.lower()
    fast_n = int(tc.isin(FAST_CLASSES).sum())
    slow_n = int(tc.isin(SLOW_CLASSES).sum())
    pace = 100 * clamp01(fast_n / max(fast_n + slow_n, 1))

    opening_counts = df[df["opening"] != "Unknown"]["opening"].value_counts()
    ent = shannon_entropy(opening_counts.tolist())
    max_ent = math.log2(max(min(len(opening_counts), 12), 2))
    breadth = 100 * clamp01(ent / max_ent) if max_ent else 50.0

    draw_rate = float((df["result"] == "draw").mean()) if n else 0.0
    decisiveness = 100 * (1.0 - draw_rate)
    endgame_reach = 100 * (float((df["n_moves"] >= 80).mean()) if n else 0.0)

    classical_keys = (
        "ruy lopez", "italian", "queen's gambit", "queens gambit",
        "ortho", "four knights", "scotch", "vienna",
    )
    hyper_keys = (
        "nimzo", "reti", "réti", "king's indian", "kings indian",
        "english", "modern", "pirc", "alekhine", "larsen", "catalan",
    )
    class_n = hyper_n = 0
    for name, cnt in opening_counts.items():
        low = str(name).lower()
        if any(k in low for k in classical_keys):
            class_n += int(cnt)
        elif any(k in low for k in hyper_keys):
            hyper_n += int(cnt)
    classical = 100 * clamp01(class_n / max(class_n + hyper_n, 1))
    if class_n + hyper_n == 0:
        classical = 50.0

    return {
        "aggression": round(aggression, 1),
        "tactics": round(tactics, 1),
        "pace": round(pace, 1),
        "breadth": round(breadth, 1),
        "decisiveness": round(decisiveness, 1),
        "endgame": round(endgame_reach, 1),
        "classical": round(classical, 1),
    }


def personality_from_axes(axes):
    pairs = [
        ("aggression", "A", "D"),
        ("tactics", "T", "S"),
        ("pace", "P", "M"),
        ("breadth", "X", "Z"),
    ]
    letters = []
    letter_axes = []
    axis_order = ["aggression", "tactics", "pace", "breadth"]
    for key, hi, lo in pairs:
        val = axes[key]
        letter = hi if val >= 50 else lo
        letters.append(letter)
        letter_axes.append((letter, abs(val - 50.0), key))

    code = "".join(letters)
    ranked = sorted(
        letter_axes,
        key=lambda t: (-t[1], axis_order.index(t[2])),
    )
    a, b = ranked[0][0], ranked[1][0]
    name = (
        ARCHETYPE_NAMES.get(a + b)
        or ARCHETYPE_NAMES.get(b + a)
        or "The Unclassified"
    )
    return code, name, ranked


def match_gm(axes, df):
    user_vec = np.array([
        axes["aggression"], axes["tactics"], axes["decisiveness"], axes["classical"]
    ], dtype=float)
    bumps = Counter()
    top_openings = (
        df[df["opening"] != "Unknown"]["opening"]
        .value_counts()
        .head(8)
        .index
        .tolist()
    )
    joined = " | ".join(str(o).lower() for o in top_openings)
    for needles, gm_names, weight in OPENING_GM_BUMPS:
        if any(n in joined for n in needles):
            for gm in gm_names:
                bumps[gm] += weight

    scored = []
    for gm in GM_PROFILES:
        dist = float(np.linalg.norm(user_vec - np.array(gm["vec"], dtype=float)))
        dist = max(0.0, dist - bumps.get(gm["name"], 0))
        scored.append((dist, gm))
    scored.sort(key=lambda t: t[0])
    return scored[0][1], scored[1][1]


def trait_lines(df, axes, stats):
    n = max(len(df), 1)
    lines = []
    tc = df["time_class"].astype(str).str.lower()
    bullet = int((tc == "bullet").sum())
    blitz = int((tc == "blitz").sum())
    rapid = int(tc.isin({"rapid", "classical"}).sum())

    if bullet / n >= 0.35:
        lines.append(("Bullet gunslinger", f"{bullet / n * 100:.0f}% of your games are bullet"))
    elif blitz / n >= 0.45:
        lines.append(("Blitz regular", f"{blitz / n * 100:.0f}% of your games are blitz"))
    elif rapid / n >= 0.40:
        lines.append((
            "Longer time control mind",
            f"{rapid / n * 100:.0f}% of your games are rapid or classical",
        ))
    else:
        fast = int(tc.isin(FAST_CLASSES).sum())
        lines.append(("Mixed tempo", f"{fast / n * 100:.0f}% bullet/blitz, the rest slower"))

    if axes["aggression"] >= 60:
        rate = pct(stats["user_captures"] + stats["user_checks"], stats["user_moves"])
        lines.append(("Hands-on attacker", f"You capture or check on {rate:.0f}% of your moves"))
    elif axes["aggression"] <= 40:
        lines.append((
            "Quiet pressure player",
            "You keep pieces on the board and poke rather than hack",
        ))
    else:
        lines.append((
            "Flexible edge",
            "Aggression sits mid-pack: sharp when it pays, solid when it does not",
        ))

    if axes["tactics"] >= 60:
        wins = max(int((df["result"] == "win").sum()), 1)
        lines.append(("Mate hunter", f"{stats['mates_delivered']} checkmates across {wins} wins"))
    elif axes["tactics"] <= 40:
        lines.append((
            "Endgame leaner",
            "Wins come more from grind and flag than flashy mates",
        ))
    else:
        lines.append(("Tactics with a plan", "You mix forcing shots with slower builds"))

    if axes["breadth"] >= 60:
        fams = int(df[df["opening"] != "Unknown"]["opening"].nunique())
        lines.append(("Opening tourist", f"{fams} different opening families in the cache"))
    else:
        top = df[df["opening"] != "Unknown"]["opening"].value_counts()
        if len(top):
            share = top.iloc[0] / top.sum() * 100
            lines.append((f"{top.index[0]} loyalist", f"{share:.0f}% of known games start in that family"))

    if axes["endgame"] >= 45:
        lines.append((
            "Deep-water sailor",
            f"{(df['n_moves'] >= 80).mean() * 100:.0f}% of games pass move 40",
        ))
    else:
        lines.append((
            "Early verdicts",
            f"Only {(df['n_moves'] >= 80).mean() * 100:.0f}% of games reach move 40",
        ))

    return lines[:5]


# ------------------------------- figures -----------------------------------
def fig_board(matrix, title, subtitle, colorscale):
    fig = go.Figure(go.Heatmap(
        z=matrix.copy(), x=FILES, y=[1, 2, 3, 4, 5, 6, 7, 8],
        colorscale=colorscale, showscale=False,
        hovertemplate="%{x}%{y}: %{z:.0f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(
            text=f"{title}<br><span style='font-size:12px;color:{MUTED}'>{subtitle}</span>",
            font=dict(size=18, color=INK),
            x=0.02, xanchor="left",
        ),
        xaxis=dict(showgrid=False, zeroline=False, side="bottom", tickfont=dict(color=MUTED)),
        yaxis=dict(showgrid=False, zeroline=False, scaleanchor="x", tickfont=dict(color=MUTED),
                   constrain="domain"),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL,
        height=480, margin=dict(l=40, r=20, t=80, b=40),
        autosize=True,
    )
    return fig


def fig_openings(df):
    sub = df[df["opening"] != "Unknown"].copy()
    if sub.empty:
        return None
    g = (sub.groupby(["color", "opening"])
            .agg(games=("result", "size"),
                 wins=("result", lambda s: (s == "win").sum()))
            .reset_index())
    g = g[g["games"] >= max(3, g["games"].quantile(0.5) * 0.15)]
    g = g.sort_values("games", ascending=False).groupby("color").head(9)
    g["winrate"] = (g["wins"] / g["games"] * 100).round(0)
    labels, parents, values, colors, custom = [], [], [], [], []
    for color in ["white", "black"]:
        root = f"as {color.title()}"
        cg = g[g["color"] == color]
        if cg.empty:
            continue
        labels.append(root)
        parents.append("")
        values.append(int(cg["games"].sum()))
        colors.append(50)
        custom.append("")
        for _, r in cg.iterrows():
            labels.append(r["opening"])
            parents.append(root)
            values.append(int(r["games"]))
            colors.append(r["winrate"])
            custom.append(f"{int(r['games'])} games, {r['winrate']:.0f}% win")
    fig = go.Figure(go.Sunburst(
        labels=labels, parents=parents, values=values, branchvalues="total",
        marker=dict(
            colors=colors,
            colorscale=[[0, RED], [0.5, GREY], [1, GREEN]],
            cmin=0, cmax=100,
            colorbar=dict(title="win %", tickfont=dict(color=MUTED)),
        ),
        customdata=custom,
        hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
        insidetextorientation="radial",
    ))
    fig.update_layout(
        title=dict(text="Openings by win rate", font=dict(size=20, color=INK)),
        paper_bgcolor=PANEL, height=620, margin=dict(l=20, r=20, t=70, b=40),
        autosize=True,
    )
    return fig


def fig_rating(df):
    sub = df.dropna(subset=["played_at", "user_rating"]).sort_values("played_at")
    if sub.empty:
        return None
    fig = go.Figure()
    palette = ["#b07d2e", "#4a9d5b", "#5a8fb0", "#a05ab0", "#b05a5a", "#8fb05a"]
    keys = sub.assign(k=sub["platform"] + " " + sub["time_class"])
    for i, (k, grp) in enumerate(keys.groupby("k")):
        if len(grp) < 20:
            continue
        grp = grp.sort_values("played_at")
        roll = grp["user_rating"].rolling(20, min_periods=5).mean()
        fig.add_trace(go.Scatter(
            x=grp["played_at"], y=roll, mode="lines", name=k,
            line=dict(width=2, color=palette[i % len(palette)]),
        ))
    fig.update_layout(
        title=dict(text="Rating over time (20-game rolling)", font=dict(size=20, color=INK)),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=420,
        xaxis=dict(gridcolor="#20242e", tickfont=dict(color=MUTED)),
        yaxis=dict(gridcolor="#20242e", tickfont=dict(color=MUTED)),
        legend=dict(font=dict(color=MUTED), orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=50, r=40, t=90, b=40),
        autosize=True,
    )
    return fig


def fig_results_by_color(df):
    fig = go.Figure()
    cmap = {"win": GREEN, "draw": GREY, "loss": RED}
    for res in ["win", "draw", "loss"]:
        vals = [((df["color"] == c) & (df["result"] == res)).sum() for c in ["white", "black"]]
        fig.add_trace(go.Bar(
            name=res.title(), x=["as White", "as Black"], y=vals, marker_color=cmap[res],
        ))
    fig.update_layout(
        barmode="stack",
        title=dict(text="Results by color", font=dict(size=18, color=INK)),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=400,
        xaxis=dict(tickfont=dict(color=MUTED)),
        yaxis=dict(gridcolor="#20242e", tickfont=dict(color=MUTED),
                   title=dict(text="games", font=dict(color=MUTED))),
        legend=dict(font=dict(color=MUTED)),
        margin=dict(l=50, r=20, t=70, b=40),
        autosize=True,
    )
    return fig


def fig_time_heatmap(df):
    sub = df.dropna(subset=["played_at"]).copy()
    if sub.empty:
        return None
    sub["dow"] = sub["played_at"].dt.dayofweek
    sub["hour"] = sub["played_at"].dt.hour
    piv = sub.pivot_table(index="dow", columns="hour", values="result",
                          aggfunc="size", fill_value=0)
    piv = piv.reindex(index=range(7), columns=range(24), fill_value=0)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fig = go.Figure(go.Heatmap(
        z=piv.values, x=[f"{h:02d}" for h in range(24)], y=days,
        colorscale=[[0, PANEL], [0.5, GOLD], [1, "#f0d090"]], showscale=False,
        hovertemplate="%{y} %{x}:00 UTC<br>%{z} games<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="When you play (UTC)", font=dict(size=18, color=INK)),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=400,
        xaxis=dict(tickfont=dict(color=MUTED), title=dict(text="hour", font=dict(color=MUTED))),
        yaxis=dict(tickfont=dict(color=MUTED)),
        margin=dict(l=50, r=20, t=70, b=50),
        autosize=True,
    )
    return fig


def fig_winrate_by_hour(df):
    sub = df.dropna(subset=["played_at"]).copy()
    if sub.empty:
        return None
    sub["hour"] = sub["played_at"].dt.hour
    g = sub.groupby("hour").agg(
        games=("result", "size"),
        wins=("result", lambda s: (s == "win").sum()),
    ).reindex(range(24), fill_value=0)
    wr = np.where(g["games"] > 0, g["wins"] / g["games"] * 100, np.nan)
    fig = go.Figure(go.Bar(
        x=[f"{h:02d}" for h in range(24)],
        y=wr,
        marker_color=GOLD,
        hovertemplate="hour %{x}:00 UTC<br>win rate %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Win rate by hour (UTC)", font=dict(size=18, color=INK)),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=400,
        xaxis=dict(tickfont=dict(color=MUTED),
                   title=dict(text="hour (UTC)", font=dict(color=MUTED))),
        yaxis=dict(gridcolor="#20242e", tickfont=dict(color=MUTED), range=[0, 100],
                   title=dict(text="win %", font=dict(color=MUTED))),
        margin=dict(l=50, r=20, t=70, b=50),
        autosize=True,
    )
    return fig


def fig_first_moves(stats):
    c = stats["first_moves_white"]
    if not c:
        return None
    order = ["e4", "d4", "Nf3", "c4", "other"]
    color_map = {
        "e4": GOLD,
        "d4": "#5a8fb0",
        "Nf3": GREEN,
        "c4": "#a05ab0",
        "other": GREY,
    }
    rows = [(k, int(c[k])) for k in order if c.get(k)]
    if not rows:
        return None
    # Ascending so the dominant first move sits at the top of a horizontal bar.
    rows.sort(key=lambda t: t[1])
    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]
    total = sum(values) or 1
    fig = go.Figure(go.Bar(
        y=labels,
        x=values,
        orientation="h",
        marker_color=[color_map.get(lab, GREY) for lab in labels],
        text=[f"{v / total * 100:.1f}%" for v in values],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{y}: %{x} games<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="First move as White", font=dict(size=18, color=INK)),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=400,
        xaxis=dict(tickfont=dict(color=MUTED), gridcolor="#20242e",
                   title=dict(text="games", font=dict(color=MUTED))),
        yaxis=dict(tickfont=dict(color=MUTED)),
        margin=dict(l=60, r=70, t=70, b=40),
        autosize=True,
    )
    return fig


def fig_weapons_nemeses(df, min_games=20):
    sub = df[df["opening"] != "Unknown"].copy()
    if sub.empty:
        return None, None
    g = (sub.groupby(["color", "opening"])
            .agg(games=("result", "size"),
                 wins=("result", lambda s: (s == "win").sum()))
            .reset_index())
    g = g[g["games"] >= min_games]
    if g.empty:
        return None, None
    g["winrate"] = g["wins"] / g["games"] * 100
    g["label"] = g["opening"] + " (" + g["color"].str.title() + ")"
    top = g.sort_values(["winrate", "games"], ascending=[False, False]).head(5)
    bot = g.sort_values(["winrate", "games"], ascending=[True, False]).head(5)

    def _bar(frame, title, color):
        if frame.empty:
            return None
        frame = frame.sort_values("winrate", ascending=True)
        fig = go.Figure(go.Bar(
            x=frame["winrate"], y=frame["label"], orientation="h",
            marker_color=color,
            customdata=np.stack([frame["games"], frame["wins"]], axis=1),
            hovertemplate="%{y}<br>%{x:.1f}% win (%{customdata[1]}/%{customdata[0]})<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text=title, font=dict(size=16, color=INK)),
            paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=340,
            xaxis=dict(range=[0, 100], gridcolor="#20242e", tickfont=dict(color=MUTED),
                       title=dict(text="win %", font=dict(color=MUTED))),
            yaxis=dict(tickfont=dict(color=MUTED), automargin=True),
            margin=dict(l=20, r=20, t=60, b=40),
            autosize=True,
        )
        return fig

    return _bar(top, "Best weapons (min 20 games)", GREEN), _bar(bot, "Nemeses (min 20 games)", RED)


# ------------------------------- extras ------------------------------------
def color_edge_card(df):
    rates = []
    for color in ("white", "black"):
        sub = df[df["color"] == color]
        rates.append(float((sub["result"] == "win").mean() * 100) if len(sub) else 0.0)
    delta = rates[0] - rates[1]
    sign = "+" if delta >= 0 else ""
    return (
        f"You score {sign}{delta:.1f}% as White",
        f"White win rate {rates[0]:.1f}% vs Black {rates[1]:.1f}%",
    )


def streak_stats(df):
    sub = df.dropna(subset=["played_at"]).sort_values("played_at")
    if sub.empty:
        return 0, 0, "none", 0
    results = sub["result"].tolist()
    best_w = best_l = cur_w = cur_l = 0
    for r in results:
        if r == "win":
            cur_w += 1
            cur_l = 0
            best_w = max(best_w, cur_w)
        elif r == "loss":
            cur_l += 1
            cur_w = 0
            best_l = max(best_l, cur_l)
        else:
            cur_w = cur_l = 0
    last = results[-1]
    if last == "win":
        i = len(results) - 1
        n = 0
        while i >= 0 and results[i] == "win":
            n += 1
            i -= 1
        return best_w, best_l, "win", n
    if last == "loss":
        i = len(results) - 1
        n = 0
        while i >= 0 and results[i] == "loss":
            n += 1
            i -= 1
        return best_w, best_l, "loss", n
    return best_w, best_l, "draw", 1


def rating_jumps(df):
    sub = df.dropna(subset=["played_at", "user_rating"]).copy()
    if sub.empty:
        return []
    sub["month"] = sub["played_at"].dt.to_period("M").astype(str)
    rows = []
    for (tc, month), grp in sub.groupby(["time_class", "month"]):
        if len(grp) < 8:
            continue
        grp = grp.sort_values("played_at")
        delta = float(grp["user_rating"].iloc[-1] - grp["user_rating"].iloc[0])
        rows.append((tc, month, delta, len(grp)))
    if not rows:
        return []
    by_tc = {}
    for tc, month, delta, n in rows:
        prev = by_tc.get(tc)
        if prev is None or delta > prev[1]:
            by_tc[tc] = (month, delta, n)
    out = []
    for tc, (month, delta, n) in sorted(by_tc.items(), key=lambda kv: -kv[1][1]):
        sign = "+" if delta >= 0 else ""
        out.append(f"{tc}: {sign}{delta:.0f} in {month} ({n} games)")
    return out[:6]


# ------------------------------- assemble ----------------------------------
def esc(s):
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def meter_html(label, value, lo_label, hi_label):
    v = max(0.0, min(100.0, float(value)))
    return f"""
    <div class="meter">
      <div class="meter-top">
        <span>{esc(label)}</span>
        <span class="meter-val">{v:.0f}</span>
      </div>
      <div class="meter-track"><div class="meter-fill" style="width:{v:.1f}%"></div></div>
      <div class="meter-ends"><span>{esc(lo_label)}</span><span>{esc(hi_label)}</span></div>
    </div>"""


def hero_card_html(axes, code, archetype, gm1, gm2, traits):
    meters = "".join([
        meter_html("Aggression", axes["aggression"], "Defender", "Attacker"),
        meter_html("Tactics vs Strategy", axes["tactics"], "Strategist", "Tactician"),
        meter_html("Pace", axes["pace"], "Marathoner", "Sprinter"),
        meter_html("Breadth", axes["breadth"], "Specialist", "Explorer"),
        meter_html("Decisiveness", axes["decisiveness"], "Drawer", "Decisive"),
        meter_html("Endgame reach", axes["endgame"], "Short games", "Deep games"),
    ])
    trait_html = "".join(
        f'<div class="trait"><div class="trait-t">{esc(t)}</div>'
        f'<div class="trait-d">{esc(d)}</div></div>'
        for t, d in traits
    )
    return f"""
    <section class="hero">
      <div class="hero-kicker">Chess personality card</div>
      <div class="hero-name">{esc(archetype)}</div>
      <div class="hero-code">{esc(code)}</div>
      <div class="gm-box">
        <div class="gm-label">Your GM double</div>
        <div class="gm-main">{esc(gm1["name"])}</div>
        <div class="gm-sub">Runner-up: {esc(gm2["name"])}</div>
        <div class="gm-note">For fun, based on your style and openings, not an engine comparison.</div>
      </div>
      <div class="traits">{trait_html}</div>
      <div class="meters">{meters}</div>
    </section>"""


def stat_cards(df):
    n = len(df)
    wins = int((df["result"] == "win").sum())
    draws = int((df["result"] == "draw").sum())
    losses = int((df["result"] == "loss").sum())
    peak = int(df["user_rating"].max()) if df["user_rating"].notna().any() else "-"
    accts = int(df["account"].nunique())
    plats = int(df["platform"].nunique())
    span = ""
    if df["played_at"].notna().any():
        lo = int(df["played_at"].min().year)
        hi = int(df["played_at"].max().year)
        span = f"{lo}\u2013{hi}"
    cards = [
        ("games analyzed", f"{n:,}"),
        ("win / draw / loss", f"{wins:,} / {draws:,} / {losses:,}"),
        ("overall win rate", f"{wins / n * 100:.1f}%" if n else "-"),
        ("peak rating", f"{peak}"),
        ("accounts", f"{accts} across {plats} site(s)"),
        ("span", span or "-"),
    ]
    html = '<div class="cards">'
    for label, val in cards:
        html += f'<div class="card"><div class="val">{val}</div><div class="lab">{label}</div></div>'
    return html + "</div>"


def fun_counters_html(stats):
    castle_n = stats["castle_king"] + stats["castle_queen"]
    if castle_n:
        ks = stats["castle_king"] / castle_n * 100
        qs = stats["castle_queen"] / castle_n * 100
        castle_txt = f"{castle_n:,}  ({ks:.0f}% O-O / {qs:.0f}% O-O-O)"
    else:
        castle_txt = "0"
    promo = stats["promotions"]
    promo_txt = ", ".join(f"{n} {p}" for p, n in promo.most_common()) if promo else "0"
    top_sq = stats["square_landed"].most_common(1)
    top_sq_txt = f"{top_sq[0][0]} ({top_sq[0][1]:,})" if top_sq else "-"
    top_piece = stats["piece_moved"].most_common(1)
    top_piece_txt = f"{top_piece[0][0]} ({top_piece[0][1]:,})" if top_piece else "-"
    mates = stats["mates_by_piece"]
    if mates:
        mate_bits = ", ".join(f"{n} by {p}" for p, n in mates.most_common())
        mate_txt = f"{stats['mates_delivered']:,} ({mate_bits})"
    else:
        mate_txt = f"{stats['mates_delivered']:,}"
    fast = stats["fastest_mate_win_moves"]
    fast_txt = f"{fast} moves" if fast is not None else "-"

    items = [
        ("total moves made", f"{stats['user_moves']:,}"),
        ("total captures", f"{stats['user_captures']:,}"),
        ("pieces lost", f"{stats['pieces_lost']:,}"),
        ("checks given", f"{stats['user_checks']:,}"),
        ("times castled", castle_txt),
        ("promotions", promo_txt),
        ("en passant", f"{stats['en_passant']:,}"),
        ("longest game", f"{stats['longest_game_moves']} plies"),
        ("fastest mate win", fast_txt),
        ("most-landed square", top_sq_txt),
        ("most-moved piece", top_piece_txt),
        ("checkmates delivered", mate_txt),
    ]
    html = '<div class="section-title">Fun counters</div><div class="cards fun">'
    for lab, val in items:
        html += (
            f'<div class="card"><div class="val small">{esc(val)}</div>'
            f'<div class="lab">{esc(lab)}</div></div>'
        )
    return html + "</div>"


def side_stats_html(df, stats):
    edge_t, edge_d = color_edge_card(df)
    bw, bl, cur_kind, cur_n = streak_stats(df)
    if cur_kind == "win":
        cur_txt = f"{cur_n}-game win streak"
    elif cur_kind == "loss":
        cur_txt = f"{cur_n}-game loss streak"
    else:
        cur_txt = "draw (streak reset)"
    jumps = rating_jumps(df)
    jumps_html = "".join(f"<li>{esc(j)}</li>" for j in jumps) if jumps else "<li>n/a</li>"

    if stats["has_any_clock"] and stats["scramble_games"]:
        scr = pct(stats["scramble_wins"], stats["scramble_games"])
        scramble_txt = (
            f"{scr:.1f}% win rate when your clock dipped under 20s "
            f"({stats['scramble_games']:,} games)"
        )
    elif stats["has_any_clock"]:
        scramble_txt = "clock data present, but no sub-20s moments found"
    else:
        scramble_txt = "n/a (no clock data in cache yet)"

    return f"""
    <div class="grid2">
      <div class="panel text-panel">
        <div class="panel-h">Color edge</div>
        <div class="big">{esc(edge_t)}</div>
        <div class="muted">{esc(edge_d)}</div>
      </div>
      <div class="panel text-panel">
        <div class="panel-h">Streaks</div>
        <div class="muted">Longest win streak</div>
        <div class="big">{bw}</div>
        <div class="muted" style="margin-top:10px">Longest loss streak</div>
        <div class="big">{bl}</div>
        <div class="muted" style="margin-top:10px">Current streak</div>
        <div class="big">{esc(cur_txt)}</div>
      </div>
    </div>
    <div class="grid2">
      <div class="panel text-panel">
        <div class="panel-h">Biggest rating jumps</div>
        <div class="muted">Best improving calendar month per time class</div>
        <ul class="clean">{jumps_html}</ul>
      </div>
      <div class="panel text-panel">
        <div class="panel-h">Time-scramble win rate</div>
        <div class="big" style="font-size:22px">{esc(scramble_txt)}</div>
        <div class="muted">Chess.com clocks come from PGN. Lichess needs a refresh with clocks=true.</div>
      </div>
    </div>
    """


def _div(fig, include_plotlyjs=False):
    if fig is None:
        return ""
    return (
        f'<div class="panel">'
        f'{pio.to_html(fig, include_plotlyjs=include_plotlyjs, full_html=False, config={"displayModeBar": False})}'
        f"</div>"
    )


def assemble_html(df, activity, captures, stats, axes, code, archetype, gm1, gm2, traits,
                  embed_plotly=False):
    cards = stat_cards(df)
    hero = hero_card_html(axes, code, archetype, gm1, gm2, traits)
    weapons, nemeses = fig_weapons_nemeses(df)
    figs = [
        fig_board(
            activity, "Where your pieces live",
            "landing squares from your side",
            [[0, PANEL], [0.4, "#3a4a6a"], [1, "#7fb0ff"]],
        ),
        fig_board(
            captures, "Where your pieces die",
            "capture squares from your side",
            [[0, PANEL], [0.4, "#6a3a3a"], [1, "#ff7f7f"]],
        ),
        fig_openings(df),
        fig_rating(df),
        fig_results_by_color(df),
        fig_time_heatmap(df),
        fig_winrate_by_hour(df),
        fig_first_moves(stats),
    ]

    body = hero
    body += cards
    body += side_stats_html(df, stats)
    body += fun_counters_html(stats)

    # Inline Plotly JS once (first chart) when building an offline file.
    plotly_pending = "inline" if embed_plotly else False

    def take(fig):
        nonlocal plotly_pending
        if fig is None:
            return ""
        if plotly_pending == "inline":
            html = _div(fig, include_plotlyjs="inline")
            plotly_pending = False
            return html
        return _div(fig, include_plotlyjs=False)

    body += '<div class="grid2">' + take(weapons) + take(nemeses) + "</div>"
    body += '<div class="grid2">' + take(figs[0]) + take(figs[1]) + "</div>"
    body += take(figs[2])
    body += take(figs[3])
    body += '<div class="grid2">' + take(figs[4]) + take(figs[5]) + "</div>"
    body += '<div class="grid2">' + take(figs[6]) + take(figs[7]) + "</div>"

    n = len(df)
    accts = int(df["account"].nunique())
    plats = int(df["platform"].nunique())
    today = date.today().strftime("%b %d, %Y")
    footer = f"Generated {today} from {n:,} games across {accts} accounts on {plats} sites."

    plotly_tag = (
        "" if embed_plotly
        else '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>\n'
    )

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chess Signature</title>
{plotly_tag}<style>
  body{{background:{BG};color:{INK};font-family:-apple-system,Segoe UI,Roboto,sans-serif;
       margin:0;padding:32px 24px 64px;}}
  .wrap{{max-width:1100px;margin:0 auto;}}
  h1{{font-size:34px;margin:0 0 4px;letter-spacing:-0.5px;}}
  .sub{{color:{MUTED};margin:0 0 28px;font-size:15px;}}
  .hero{{background:linear-gradient(160deg,#161a24 0%,{PANEL} 55%,#10131a 100%);
         border:1px solid #2a3142;border-radius:18px;padding:28px 28px 22px;margin-bottom:28px;
         box-shadow:0 12px 40px rgba(0,0,0,0.35);}}
  .hero-kicker{{color:{MUTED};text-transform:uppercase;letter-spacing:1.4px;font-size:11px;margin-bottom:8px;}}
  .hero-name{{font-size:42px;font-weight:700;color:{GOLD};letter-spacing:-0.8px;line-height:1.1;}}
  .hero-code{{display:inline-block;margin-top:10px;padding:6px 12px;border:1px solid {GOLD};
              border-radius:8px;color:{GOLD};font-weight:600;letter-spacing:3px;font-size:18px;}}
  .gm-box{{margin-top:22px;padding-top:18px;border-top:1px solid #242a38;}}
  .gm-label{{color:{MUTED};font-size:12px;text-transform:uppercase;letter-spacing:0.8px;}}
  .gm-main{{font-size:26px;font-weight:600;margin-top:4px;}}
  .gm-sub{{color:{MUTED};margin-top:4px;}}
  .gm-note{{color:{MUTED};font-size:12px;margin-top:8px;font-style:italic;}}
  .traits{{display:grid;grid-template-columns:1fr;gap:10px;margin-top:22px;}}
  .trait{{background:rgba(11,13,17,0.45);border:1px solid #1e2330;border-radius:10px;padding:12px 14px;}}
  .trait-t{{font-weight:600;color:{INK};}}
  .trait-d{{color:{MUTED};font-size:13px;margin-top:3px;}}
  .meters{{display:grid;grid-template-columns:1fr 1fr;gap:14px 22px;margin-top:22px;}}
  .meter-top{{display:flex;justify-content:space-between;font-size:12px;color:{MUTED};margin-bottom:4px;}}
  .meter-val{{color:{GOLD};font-weight:600;}}
  .meter-track{{height:8px;background:#1e2330;border-radius:99px;overflow:hidden;}}
  .meter-fill{{height:100%;background:linear-gradient(90deg,#6a4a1e,{GOLD});border-radius:99px;}}
  .meter-ends{{display:flex;justify-content:space-between;font-size:10px;color:#5b6172;margin-top:3px;}}
  .cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:28px;}}
  .cards.fun{{grid-template-columns:repeat(3,1fr);}}
  .card{{background:{PANEL};border:1px solid #1e2330;border-radius:14px;padding:18px 20px;}}
  .card .val{{font-size:26px;font-weight:600;color:{GOLD};}}
  .card .val.small{{font-size:18px;line-height:1.25;}}
  .card .lab{{font-size:12px;color:{MUTED};text-transform:uppercase;letter-spacing:0.6px;margin-top:4px;}}
  .panel{{background:{PANEL};border:1px solid #1e2330;border-radius:14px;padding:10px 14px;margin-bottom:22px;overflow:visible;}}
  .panel .js-plotly-plot,.panel .plotly-graph-div{{max-width:100%;}}
  .text-panel{{padding:18px 20px;}}
  .panel-h{{font-size:18px;font-weight:600;margin-bottom:8px;}}
  .big{{font-size:28px;font-weight:600;color:{GOLD};}}
  .muted{{color:{MUTED};font-size:13px;}}
  .section-title{{font-size:20px;font-weight:600;margin:8px 0 14px;}}
  ul.clean{{margin:10px 0 0;padding-left:18px;color:{INK};}}
  ul.clean li{{margin:6px 0;}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:start;}}
  .grid2 > .panel{{min-width:0;}}
  .footer{{color:{MUTED};font-size:13px;margin-top:12px;text-align:center;}}
  @media(max-width:820px){{
    .grid2,.meters,.cards,.cards.fun{{grid-template-columns:1fr;}}
    .hero-name{{font-size:32px;}}
    body{{padding:20px 14px 48px;}}
  }}
</style></head><body><div class="wrap">
  <h1>Chess Signature</h1>
  <p class="sub">Every rated game across your accounts, turned into one picture.</p>
  {body}
  <p class="footer">{esc(footer)}</p>
</div></body></html>"""


def build_html(games, embed_plotly=False):
    """Build the full chess signature HTML string from a list of game records."""
    if not games:
        raise ValueError("No games to render.")
    df, activity, captures, stats = build_frame(games)
    axes = compute_axes(df, stats)
    code, archetype, _ = personality_from_axes(axes)
    gm1, gm2 = match_gm(axes, df)
    traits = trait_lines(df, axes, stats)
    return assemble_html(
        df, activity, captures, stats, axes, code, archetype, gm1, gm2, traits,
        embed_plotly=embed_plotly,
    )


def build_html_pair(games):
    """One board walk, then CDN + offline HTML strings."""
    if not games:
        raise ValueError("No games to render.")
    df, activity, captures, stats = build_frame(games)
    axes = compute_axes(df, stats)
    code, archetype, _ = personality_from_axes(axes)
    gm1, gm2 = match_gm(axes, df)
    traits = trait_lines(df, axes, stats)
    args = (df, activity, captures, stats, axes, code, archetype, gm1, gm2, traits)
    return (
        assemble_html(*args, embed_plotly=False),
        assemble_html(*args, embed_plotly=True),
    )


def main():
    games = load_games()
    if not games:
        raise SystemExit("Cache is empty. Run fetch_games.py first.")
    print(f"Parsing {len(games):,} games...")
    html = build_html(games, embed_plotly=False)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    if "\ufffd" in html:
        print("WARNING: replacement character U+FFFD found in output")
    else:
        print("UTF-8 check ok (no U+FFFD)")
    # Light sanity: personality card present
    if "Chess personality card" in html:
        print("Personality card: ok")
    if "\u2013" in html:
        print("SPAN en dash: ok")
    print(f"Wrote {OUT_FILE}  ->  open it in your browser.")


if __name__ == "__main__":
    main()
