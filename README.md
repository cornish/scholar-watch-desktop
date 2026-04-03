# Scholar Watch Desktop

A desktop app that tracks Google Scholar citation metrics over time. Monitor h-index, citation counts, publication trends, and more for any researcher — all from your local machine.

**Why desktop?** Google Scholar blocks requests from cloud server IPs. Running locally means scraping works reliably from your own network.

## Features

- **Track any researcher** by Google Scholar ID or profile URL
- **Citation metrics** — total citations, h-index, i10-index, citation velocity, acceleration, half-life
- **Interactive charts** — citation timelines, h-index trends, velocity, citations per year, top papers (Plotly)
- **h-index analysis** — boundary visualization, candidate papers with estimated days to next h
- **Trending & declining papers** — ranked by citation velocity
- **Researcher comparison** — side-by-side metrics and overlay charts
- **Notifications** — alerts for h-index changes, citation milestones, new publications
- **Scrape from the UI** — one-click data refresh with background processing
- **Full CLI** — `scholar-watch scrape`, `metrics`, `add-researcher`, etc.

## Quick Start

### Option 1: Download the exe (Windows)

Grab `ScholarWatch.exe` from the [latest release](../../releases/latest). Double-click to run — no Python needed.

Data is stored in `%LOCALAPPDATA%\ScholarWatch\`.

### Option 2: Run from source

```bash
git clone https://github.com/cornish/scholar-watch-desktop.git
cd scholar-watch-desktop
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate # Linux/Mac
pip install -e .
scholar-watch init-db
scholar-watch desktop
```

## Usage

1. **Add researchers** — paste a Scholar ID (e.g. `g9uuZu6YAAAAJ`) or full profile URL
2. **Scrape** — click "Scrape All" to fetch data from Google Scholar
3. **Explore** — click a researcher to see charts, metrics, trending papers, and h-index analysis
4. **Compare** — select multiple researchers for side-by-side comparison
5. **Notifications** — bell icon shows unread alerts for milestones and changes

## CLI Commands

```
scholar-watch desktop           # Launch the desktop app
scholar-watch scrape            # Scrape all tracked researchers
scholar-watch scrape -r ID      # Scrape a single researcher
scholar-watch metrics ID        # Print metrics for a researcher
scholar-watch add-researcher ID # Add a researcher by Scholar ID
scholar-watch list-researchers  # List all tracked researchers
scholar-watch init-db           # Initialize the database
scholar-watch report            # Send an email report
```

## Configuration

Copy `config/config.example.yaml` to `config/config.yaml` and edit as needed:

```yaml
database:
  path: data/scholar_watch.db

scraping:
  min_delay: 5
  max_delay: 15
  max_publications: 500
```

Environment variables can be interpolated with `${VAR_NAME}` syntax.

## Architecture

```
Chrome/Edge Window (Eel)
├── Static HTML + CSS + JS
├── Plotly.js charts (rendered client-side from JSON)
└── eel.function() calls ──WebSocket──► Python backend
                                        ├── @eel.expose API functions
                                        ├── scholarly (Google Scholar scraper)
                                        ├── SQLAlchemy + SQLite
                                        ├── Plotly figure generation
                                        └── Metrics computation
```

Built with [Eel](https://github.com/python-eel/Eel), [scholarly](https://github.com/scholarly-python-package/scholarly), [Plotly](https://plotly.com/python/), and [SQLAlchemy](https://www.sqlalchemy.org/).

## License

[GPL-3.0](LICENSE)
