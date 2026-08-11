"""
Streamlit front-end for Chess Signature.
Run:  streamlit run app.py
"""

import streamlit as st
import streamlit.components.v1 as components

import report_cache
from fetch_games import fetch_all
from make_signature import build_html_pair

MAX_ACCOUNTS = 6

PAGE_CSS = """
<style>
  /* Clear Streamlit top chrome so the hero border is not clipped */
  .block-container {
    padding-top: 3.25rem !important;
    padding-bottom: 4rem !important;
    max-width: 920px;
  }
  [data-testid="stHeader"] {
    background: transparent;
  }
  [data-testid="stToolbar"] { right: 1rem; }
  #MainMenu { visibility: hidden; }
  footer { visibility: hidden; }
  /* Drop default empty top gap that fights our padding */
  div[data-testid="stVerticalBlock"] > div:first-child { gap: 0.5rem; }

  .cs-hero {
    background: linear-gradient(160deg, #161a24 0%, #13161d 55%, #10131a 100%);
    border: 1px solid #2a3142;
    border-radius: 16px;
    padding: 1.5rem 1.6rem 1.35rem;
    margin: 0 0 1.75rem 0;
    box-sizing: border-box;
  }
  .cs-kicker {
    color: #8b93a7;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    font-size: 0.72rem;
    margin: 0 0 0.45rem 0;
  }
  .cs-title {
    font-size: 2rem;
    font-weight: 700;
    color: #b07d2e;
    letter-spacing: -0.4px;
    margin: 0 0 0.45rem 0;
    line-height: 1.15;
  }
  .cs-sub {
    color: #a0a7b8;
    font-size: 0.98rem;
    margin: 0;
    line-height: 1.45;
    max-width: 40rem;
  }
  .cs-pill-row {
    margin-top: 1rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
  }
  .cs-pill {
    border: 1px solid #2a3142;
    color: #c5cad6;
    border-radius: 999px;
    padding: 0.22rem 0.7rem;
    font-size: 0.78rem;
    background: rgba(11,13,17,0.45);
  }
  .cs-note {
    color: #8b93a7;
    font-size: 0.85rem;
    margin: 0.75rem 0 0 0;
    line-height: 1.4;
  }
  .cs-footer {
    color: #5b6172;
    font-size: 0.8rem;
    text-align: center;
    margin-top: 2.5rem;
    padding-top: 1rem;
    border-top: 1px solid #1e2330;
  }
  .cs-footer a { color: #8b93a7; text-decoration: none; }
  .cs-footer a:hover { color: #b07d2e; }

  /* Tighter, quieter form controls */
  div[data-testid="stTextInput"] label {
    color: #c5cad6 !important;
    font-weight: 500 !important;
  }
  div[data-testid="stExpander"] {
    border: 1px solid #1e2330 !important;
    border-radius: 10px !important;
    background: transparent !important;
  }
  div[data-testid="stExpander"] details {
    border: none !important;
  }
</style>
"""


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


def session_key(chesscom, lichess, token, max_games):
    return (
        tuple(sorted(u.lower() for u in chesscom)),
        tuple(sorted(u.lower() for u in lichess)),
        token or "",
        int(max_games),
    )


def render_hero():
    st.markdown(
        """
        <div class="cs-hero">
          <div class="cs-kicker">Chess analytics</div>
          <div class="cs-title">Chess Signature</div>
          <p class="cs-sub">
            Public games in. One personality page out. Screenshot it, download it,
            send it to a friend.
          </p>
          <div class="cs-pill-row">
            <span class="cs-pill">Personality card</span>
            <span class="cs-pill">GM double</span>
            <span class="cs-pill">Board heatmaps</span>
            <span class="cs-pill">Openings &amp; streaks</span>
            <span class="cs-pill">Offline HTML</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(
        page_title="Chess Signature",
        page_icon="♟",
        layout="centered",
        initial_sidebar_state="collapsed",
        menu_items={
            "Get help": "https://github.com/ahmed5145/chess_signature",
            "Report a bug": "https://github.com/ahmed5145/chess_signature/issues",
            "About": (
                "Chess Signature builds a personality report from your public "
                "Chess.com and Lichess games."
            ),
        },
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    render_hero()

    chesscom_raw = st.text_input(
        "Chess.com usernames",
        placeholder="comma-separated, e.g. Hikaru",
        help="Up to 6 accounts total across both sites.",
    )
    lichess_raw = st.text_input(
        "Lichess usernames",
        placeholder="comma-separated, e.g. drnykterstein",
        help="Optional. Same 6-account cap shared with Chess.com.",
    )

    with st.expander("Advanced options"):
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
        force_refresh = st.checkbox(
            "Force refresh (ignore server cache)",
            value=False,
            help="Bypass the shared server cache and fetch games again.",
        )

    if "report_cache" not in st.session_state:
        st.session_state.report_cache = {}

    generate = st.button("Generate report", type="primary")
    st.markdown(
        '<p class="cs-note">Large accounts can take a few minutes on first run. '
        "Repeat lookups for the same usernames reuse a server cache for about "
        "6 hours. Times are UTC. Style matches are for fun, not engine strength.</p>",
        unsafe_allow_html=True,
    )

    chesscom = parse_usernames(chesscom_raw)
    lichess = parse_usernames(lichess_raw)
    active = None
    cache_note = None

    if generate:
        if not chesscom and not lichess:
            st.error("Enter at least one Chess.com or Lichess username.")
            st.stop()
        if len(chesscom) + len(lichess) > MAX_ACCOUNTS:
            st.error(f"Cap is {MAX_ACCOUNTS} accounts total. Trim the list and try again.")
            st.stop()

        key = session_key(chesscom, lichess, lichess_token, lichess_max)
        cid = report_cache.cache_id(chesscom, lichess, lichess_token or "", lichess_max)
        cached = None if force_refresh else st.session_state.report_cache.get(key)

        if cached is None and not force_refresh:
            disk_hit = report_cache.load_report(cid)
            if disk_hit is not None:
                cached = disk_hit
                st.session_state.report_cache[key] = cached
                cache_note = "Loaded from server cache (shared across sessions, ~6h TTL)."

        if cached is None:
            if force_refresh:
                report_cache.clear_report(cid)

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
                st.stop()

            missing = empty_accounts(chesscom, lichess, games)
            if missing:
                st.warning(
                    "No games from: "
                    + ", ".join(missing)
                    + ". Building the report from the accounts that did return games."
                )

            with st.spinner("Building report..."):
                html, offline_html = build_html_pair(games)

            cached = {
                "games": games,
                "html": html,
                "offline_html": offline_html,
            }
            st.session_state.report_cache[key] = cached
            report_cache.save_report(cid, cached)
            cache_note = "Fetched fresh and saved to server cache."
        elif cache_note is None:
            cache_note = "Using cached report for this username set (this session)."

        st.session_state["active_key"] = key
        active = cached

    elif st.session_state.get("active_key") in st.session_state.report_cache:
        active = st.session_state.report_cache[st.session_state["active_key"]]

    if active:
        games = active["games"]
        if cache_note:
            st.caption(cache_note)
        top_l, top_r = st.columns([3, 1])
        with top_l:
            st.success(f"Report ready from {len(games):,} games.")
        with top_r:
            st.download_button(
                "Download HTML",
                data=active["offline_html"].encode("utf-8"),
                file_name="chess_signature.html",
                mime="text/html",
                use_container_width=True,
            )
        components.html(active["html"], height=14000, scrolling=True)

    st.markdown(
        '<p class="cs-footer">Open source on GitHub · '
        '<a href="https://github.com/ahmed5145/chess_signature">'
        "ahmed5145/chess_signature</a></p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
