# Chess Signature

Pulls every rated game across your Chess.com and Lichess accounts and turns them
into one self-contained HTML page: opening repertoire, a board heatmap of where
your pieces live and die, rating over time, results by color, and when you play.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Use
1. Open `fetch_games.py` and put your usernames in `CHESSCOM_USERS` and `LICHESS_USERS`.
2. Pull and cache your games (run once, refresh anytime):
   ```bash
   python fetch_games.py
   ```
3. Build the page:
   ```bash
   python make_signature.py
   ```
4. Open `chess_signature.html` in your browser.

The fetch step caches to `games_cache.json`, so you can re-run `make_signature.py`
as many times as you want while tweaking visuals without re-hitting the APIs.

Optional: set a Lichess token for a higher rate limit:
`export LICHESS_TOKEN=xxxxx` before running fetch.
