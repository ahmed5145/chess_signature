"""
Streamlit front-end for Chess Signature.
Run:  streamlit run app.py
"""

import streamlit as st
import streamlit.components.v1 as components

from fetch_games import fetch_all
from make_signature import build_html_pair

MAX_ACCOUNTS = 6


def parse_usernames(raw: str) -> list[str]:
    """Trim, drop blanks, dedupe case-insensitively, preserve first spelling."""
    seen = set()
    out = []
    for part in (raw or "").replace(";", ",").split(","):
        name = part.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def empty_accounts(chesscom, lichess, games):
    """Return labels for requested accounts that contributed zero games."""
    missing = []
    for u in chesscom:
        n = sum(
            1 for g in games
            if g.get("platform") == "chess.com" and g.get("account", "").lower() == u.lower()
        )
        if n == 0:
            missing.append(f"chess.com/{u}")
    for u in lichess:
        n = sum(
            1 for g in games
            if g.get("platform") == "lichess" and g.get("account", "").lower() == u.lower()
        )
        if n == 0:
            missing.append(f"lichess/{u}")
    return missing


def cache_key(chesscom, lichess, token, max_games):
    return (
        tuple(sorted(u.lower() for u in chesscom)),
        tuple(sorted(u.lower() for u in lichess)),
        token or "",
        int(max_games),
    )


def main():
    st.set_page_config(page_title="Chess Signature", page_icon="♟", layout="wide")
    st.title("Chess Signature")
    st.caption("Paste your usernames. Get one shareable chess personality page.")

    chesscom_raw = st.text_input(
        "Chess.com usernames (comma separated)",
        placeholder="e.g. Hikaru, GothamChess",
    )
    lichess_raw = st.text_input(
        "Lichess usernames (comma separated)",
        placeholder="e.g. drnykterstein",
    )

    with st.expander("Advanced"):
        lichess_token = st.text_input(
            "Lichess API token (optional)",
            type="password",
            help="Raises your Lichess rate limit. Create one at lichess.org/account/oauth/token",
        )
        lichess_max = st.slider(
            "Max Lichess games per account",
            min_value=1000,
            max_value=10000,
            value=5000,
            step=500,
        )

    if "report_cache" not in st.session_state:
        st.session_state.report_cache = {}

    generate = st.button("Generate report", type="primary")
    st.caption(
        "Fetch can take a few minutes for large accounts. Times are UTC. "
        "This is for fun, not an engine analysis."
    )

    chesscom = parse_usernames(chesscom_raw)
    lichess = parse_usernames(lichess_raw)

    active = None

    if generate:
        if not chesscom and not lichess:
            st.error("Enter at least one Chess.com or Lichess username.")
            return
        if len(chesscom) + len(lichess) > MAX_ACCOUNTS:
            st.error(f"Cap is {MAX_ACCOUNTS} accounts total. Trim the list and try again.")
            return

        key = cache_key(chesscom, lichess, lichess_token, lichess_max)
        cached = st.session_state.report_cache.get(key)

        if cached is None:
            progress_bar = st.progress(0, text="Starting fetch...")
            status_box = st.status("Fetching games...", expanded=True)

            def on_progress(msg, frac):
                status_box.write(msg)
                if frac is not None:
                    progress_bar.progress(min(max(float(frac), 0.0), 1.0), text=msg)

            games = fetch_all(
                chesscom,
                lichess,
                lichess_token=lichess_token or "",
                lichess_max=lichess_max,
                progress=on_progress,
                cache={"games": [], "chesscom_months_done": {}},
            )
            progress_bar.progress(1.0, text="Fetch complete")
            status_box.update(label="Fetch complete", state="complete", expanded=False)

            if not games:
                missing = empty_accounts(chesscom, lichess, games)
                named = ", ".join(missing) if missing else "the usernames you entered"
                st.error(
                    f"No games found for {named}. "
                    "Check the spelling, or whether the account is private / has no public games."
                )
                return

            missing = empty_accounts(chesscom, lichess, games)
            if missing:
                st.warning(
                    "No games from: "
                    + ", ".join(missing)
                    + ". Building the report from the accounts that did return games."
                )

            with st.spinner("Building report (board walk + charts)..."):
                html, offline_html = build_html_pair(games)

            cached = {
                "games": games,
                "html": html,
                "offline_html": offline_html,
            }
            st.session_state.report_cache[key] = cached
        else:
            st.info("Using cached report for this username set (same session).")

        st.session_state["active_key"] = key
        active = cached

    elif st.session_state.get("active_key") in st.session_state.report_cache:
        active = st.session_state.report_cache[st.session_state["active_key"]]

    if active:
        games = active["games"]
        st.success(f"Report ready from {len(games):,} games.")
        st.download_button(
            "Download report",
            data=active["offline_html"].encode("utf-8"),
            file_name="chess_signature.html",
            mime="text/html",
        )
        components.html(active["html"], height=6000, scrolling=True)


if __name__ == "__main__":
    main()
