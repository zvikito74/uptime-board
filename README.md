# uptime-board

A small status page. It requests a list of websites on a schedule, records whether each
one answered and how fast, and shows the current status, 24-hour uptime and recent
response times in the browser.

## Stack

| Part | Technology |
| --- | --- |
| Backend | Python, Flask, Gunicorn |
| Storage | SQLite (in a Docker volume) |
| Frontend | HTML, CSS, JavaScript |
| Web server | Nginx (serves the frontend, proxies `/api` to the backend) |
| CI | GitHub Actions |

## Run it

```bash
docker compose up -d --build
```

Open <http://localhost:8090>. Three sites are monitored to start with; add your own
with the form.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness check |
| GET | `/api/targets` | All sites with status, uptime and recent checks |
| POST | `/api/targets` | Add a site: `{"name": "...", "url": "https://..."}` |
| DELETE | `/api/targets/<id>` | Stop monitoring a site |
| POST | `/api/check` | Run all checks now |

## How it works

- A background thread in the API runs every `CHECK_INTERVAL` seconds. For each site it
  makes one GET request with a 5-second timeout. A status code below 400 counts as up;
  an error code, a timeout or a failed connection counts as down.
- Every result is one row in SQLite. Uptime is the share of successful checks in the
  last 24 hours. Rows older than 7 days are deleted.
- Gunicorn runs a single worker on purpose: with several workers each one would start
  its own checker thread and every site would be checked several times.
- The browser never talks to the backend directly. Nginx serves the static files and
  forwards `/api/` to the `api` container, so only one port is published.
- `depends_on` with `condition: service_healthy` makes the web container wait until
  the API's health check passes.

## Tests

```bash
pip install -r backend/requirements.txt pytest
pytest backend
```

The tests replace the real HTTP check with a fake one, so they need no network.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHECK_INTERVAL` | `30` | Seconds between check runs |
| `SEED_TARGETS` | – | Sites added on first start, as `Name|url,Name|url` |
| `DB_PATH` | `/data/uptime.db` | SQLite file location |
