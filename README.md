# Out Tonight

A small shared dashboard for a three-stop bar crawl. The host can check in at a stop or opt in to sharing browser GPS; friends use a view-only link to see the latest status and map.

## Run locally

Requires Python 3.14 or newer and `uv`.

```sh
uv sync
uv run streamlit run streamlit_app.py
```

Open the app, name the three stops, and start a crawl. Copy the crew link for friends. Check-ins share the chosen stop; GPS sharing is off by default and can be paused at any time. Browser GPS requires location permission and a secure context (HTTPS, or localhost).

## Deployment

The app stores crawl state in SQLite. Set `CRAWL_DB_PATH` to a writable persistent location when deploying, and back it up according to your needs. SQLite must be available to every app replica using the same database file, so use a single app instance unless you replace the storage layer with a network database. Anyone with a crew link can see its check-ins and shared coordinates; share it only with your group.
