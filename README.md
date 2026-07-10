# HTRMoPo App

Document, upload, version, and browse [Kraken](https://kraken.re) HTR/OCR models using
the [HTRMoPo](https://github.com/mittagessen/HTRMoPo) metadata scheme, publishing to
Zenodo (with a citable DOI) via OAuth.

- Backend: FastAPI + SQLAlchemy (async) + SQLite, in `backend/`.
- Frontend: Vite + Vue 3 + vue-i18n (English/French), in `frontend/`, styled with a
  design system adapted from [htr-united.github.io](https://github.com/HTR-United/htr-united.github.io).
- Vendored HTRMoPo schema/vocab files live in `backend/app/schema/` (see `NOTICE.md`
  there for attribution — Apache-2.0).

## One-time setup: Zenodo OAuth application

This app authenticates users against Zenodo via OAuth2 (scopes `deposit:write` +
`deposit:actions`). You must register an OAuth application yourself (this can't be
automated):

1. Sandbox (recommended for development/testing): create an account at
   https://sandbox.zenodo.org, then register an application at
   https://sandbox.zenodo.org/account/settings/applications/. Set the redirect URI to
   `http://localhost:8000/api/auth/zenodo/callback` (or your deployment's equivalent).
2. Production: same steps at https://zenodo.org/account/settings/applications/, only
   once you're ready to publish real models.
3. Note the client ID/secret into your `.env` (see `.env.example` /
   `backend/.env.example`).

Sandbox data is not durable — Zenodo can wipe it at any time. Never treat a sandbox DOI
as a permanent citation.

## Development

Backend:

```sh
cd backend
python3 -m venv env
./env/bin/pip install -e .
cp .env.example .env   # fill in ZENODO_SANDBOX_CLIENT_ID/SECRET
./env/bin/alembic upgrade head
./env/bin/uvicorn app.main:app --reload
```

Frontend (in a second terminal; proxies `/api` to the backend on :8000):

```sh
cd frontend
npm install
npm run dev
```

### Database migrations

Schema changes go through Alembic:

```sh
cd backend
./env/bin/alembic revision --autogenerate -m "describe the change"
./env/bin/alembic upgrade head
```

## Running with Docker

```sh
cp .env.example .env   # fill in Zenodo OAuth credentials
make build
make up
```

The SQLite database is written to `./data/htrmopo-app.db` on the host (via the
`./data:/data` volume mount in `docker-compose.yml`), so it's directly readable/
backupable without entering the container. If you ran the container without that
mount, `make db-pull` copies it out. `make db-shell` opens `sqlite3` on it directly.
Draft files staged before publish live under `./data/uploads/`, in the same volume.

## Production notes

- The container runs as a non-root user (`app`, uid 1000). Its entrypoint fixes
  `/data` ownership on startup (Docker/your host may create a fresh bind-mount
  directory as root), so you don't need to manually `chown` `./data` first.
- `GET /healthz` checks DB connectivity; the image's `HEALTHCHECK` polls it.
- Uploads are streamed to disk (not buffered in memory) and capped by
  `MAX_UPLOAD_MB` (default 5120 = 5GB); Zenodo itself allows up to 50GB/file.
  Raise or lower this based on how large your models are and how much disk
  `./data` has available — draft files are staged there until published.
- If `ZENODO_ENV=production`, the app refuses to start with the default
  `SESSION_SECRET` — you must set a real random value first.
- Still missing for a fully hardened production deployment: TLS termination
  (put a reverse proxy in front), rate limiting on the Zenodo-facing endpoints,
  and structured/shipped logging.

## Deploying under a URL subfolder

If the app doesn't own its own domain (e.g. it's served at `https://example.com/plop/`
behind a reverse proxy), set `URL_BASE_PATH=/plop` in `.env` before building — this is
threaded through to both the Vite build (`VITE_BASE_PATH` build arg, so all asset URLs
and client-side routing are subfolder-aware) and FastAPI (`root_path`, so redirects like
the OAuth callback are generated correctly).

## Testing against Zenodo sandbox

`ZENODO_ENV=sandbox` (the default) points every Zenodo API call at
`sandbox.zenodo.org`. Log in via "Connect with Zenodo", create a model card, attach a
(small, throwaway) file, and publish — this exercises the full deposition create →
upload → metadata → publish flow, and "publish a new version" exercises the
versioning flow, against sandbox instead of production.

Automated test suites (pytest, frontend unit tests, e2e) are intentionally not part of
this initial pass — see the project plan for why; they'll be added once the app itself
has been reviewed.

## Catalog sync with the public HTRMoPo community

In addition to models published through this app, the catalog also mirrors the public
`ocr_models` Zenodo community (the same one HTRMoPo itself reads from), harvested via
OAI-PMH — always against real production Zenodo, regardless of this deployment's
`ZENODO_ENV`, since that community only meaningfully exists there. Both current
v1-schema records (Markdown model card + `README.md`) and legacy v0-schema records (a
standalone `metadata.json`, only ever kraken text-recognition models) are picked up; v0
metadata is converted to the v1 shape on read (see `card.v0_to_v1_metadata`) and its
version is tagged `schema_version = "v0"`. This app never *writes* v0 metadata —
publishing is always v1 — so a legacy record's owner can upgrade it to the current
schema by publishing a new (v1) version of it: see "My Models", where their own legacy
records surface with an **Upgrade to current schema** action (`app/claim.py`).

This sync runs:
- **After every publish** through this app (fire-and-forget, doesn't block the
  publish response) — a publish is already a moment we're talking to Zenodo.
- **Once a day** (`NIGHTLY_HARVEST_HOUR_UTC`, default 02:00 UTC) via an in-process
  `asyncio` task started with the app — no OS-level cron needed. Disable with
  `ENABLE_NIGHTLY_HARVEST=false`.
- **On demand** via the "Refresh from Zenodo" button on the catalog page, or
  `POST /api/models/harvest` — **admin-only** (see below), since it fans out to an
  external OAI-PMH harvest plus a metadata file (`README.md`/`metadata.json`) fetch per record.

Harvested records never overwrite ones actually owned by a user through this app (tracked
via `model_records.source`, `"app"` vs `"harvested"`) — harvesting only fills in/refreshes
records nobody here has published themselves.

## HTR-United dataset catalog cache

The "Training datasets" search box in the model form is backed by the real
[HTR-United catalog](https://htr-united.github.io/htr-united/catalog.json), cached to a
local JSON file (`./data/htr_united_cache.json` — same volume as the SQLite DB, so it
survives restarts) rather than refetched on every page load. Refreshed via conditional
GET (ETag/Last-Modified, so an unchanged upstream catalog costs almost nothing):
- **Once a day**, in the same nightly loop as the Zenodo catalog harvest above.
- **On demand** via the "Refresh HTR-United datasets" button on the catalog page, or
  `POST /api/meta/datasets/refresh` — **admin-only**, same reasoning as the Zenodo one.

## Admin users

Base (logged-in) users can publish/version their own models but can't trigger an on-demand
catalog refresh — that's gated behind `users.is_admin`, since it's a heavier, externally-facing
operation. There's no in-app way to grant admin (avoids a chicken-and-egg bootstrap problem);
toggle it via the Makefile instead:

```sh
make list-users               # find the id of the user to promote
make set-admin ID=1           # grant admin (ADMIN=true is the default)
make set-admin ID=1 ADMIN=false  # revoke
```

## Funding

<table border="0">
  <tr>
    <td rowspan="2"><img src="https://atrium-research.eu/assets/content/en/pages/communications-kit/clay.png" alt="ATRIUM" height="80"></td>
    <td>This project is developed in the context of <a href="https://atrium-research.eu/">ATRIUM</a>.</td>
  </tr>
  <tr>
    <td> ATRIUM is funded by the European Union under Grant Agreement n. 101132163. Views and opinions expressed are however those of the author(s) only and do not necessarily reflect those of the European Union. Neither the European Union nor the granting authority can be held responsible for them.</td>
  </tr>
</table>
