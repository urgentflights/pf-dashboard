# PF Dashboard

ParaFlight Aero ops site. One login covers two dashboards:

- **NKR Dashboard** (`/nkr`) — every upcoming and recent National Kidney Registry organ move, who is on the trip, and the Airspace driver or flight when automation has filled it in.
- **PF Dashboard** (`/pf`) — other organ, air ambulance, and corporate trips entered by the team.

After sign-in, `/` is a home switcher. The header shows **ParaFlight** and a switcher between the two dashboards.

The app is a single Python process (`server.py`) with no build step. On Render it uses Postgres. On a laptop, with `DATABASE_URL` unset, it uses a local SQLite file. NKR moves and PF trips are stored in separate tables.

Do not commit operational move logs. The sample CSV that shaped the columns stays out of this repo.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INGEST_TOKEN='choose-a-token'
export SECRET_KEY='choose-a-secret'
# Optional: first sign-up with this email becomes admin if none exists yet.
export ADMIN_EMAIL='Sim@paraflight.aero'
python3 server.py
```

Open http://localhost:10000 . The process listens on `0.0.0.0` and `$PORT` (default `10000`).

```bash
python3 -m unittest tests.test_ingest tests.test_tabs tests.test_auth tests.test_trips -v
```

## Environment variables

| Variable | Where it comes from | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Render Blueprint `fromDatabase` (`connectionString`). Unset locally. | Postgres URL. A `postgres://` or `postgresql://` URL uses Postgres (TLS when the host is external). Unset, or a `sqlite:///` URL, uses SQLite at `data/pf.sqlite`. |
| `ADMIN_EMAIL` | Set on the service (`Sim@paraflight.aero`). | If no admin exists yet, a sign-up with this email (case-insensitive) is activated as admin. |
| `ALLOW_TEAM_PASSWORD` | Defaults to off. | When `true`/`1`/`on`, the old shared `TEAM_PASSWORD` login still works as a fallback. Leave it off in production. |
| `TEAM_PASSWORD` | You type it in the Dashboard when the Blueprint is first created (`sync: false`). | Used only when `ALLOW_TEAM_PASSWORD` is on. |
| `INGEST_TOKEN` | Render generates it (`generateValue`). Copy it from the service Environment tab. | Bearer token for the ingest API and `POST /api/admin/bootstrap`. |
| `SECRET_KEY` | Render generates it (`generateValue`). | Signs the session cookie. |
| `PORT` | Set by Render. | HTTP port. |
| `RENDER` | Set by Render to `true`. | Marks the session cookie Secure. |

Leave `DATABASE_URL` unset on a laptop. The Render database allow list is empty, so only services on Render's private network can open it. The web service uses the internal connection string.

Shared team-password login is off unless `ALLOW_TEAM_PASSWORD` is set. If `INGEST_TOKEN` is unset, ingest and bootstrap return 401.

## NKR Dashboard

The default view groups legs by `pickup_date` from today forward. Today is the calendar date in `America/New_York`, not the laptop's zone. Pickup and delivery times are shown as stored, including the zone abbreviation in the string. History shows earlier pickup dates. A leg with no pickup date stays on the upcoming board so it is not hidden.

Summary tiles, counted across the whole log (filters do not change them):

- **Moves today** — `pickup_date` is today in New York, and status is not Removed.
- **Next 3 days** — tomorrow through three days out, status not Removed. Today is not included.
- **Unassigned** — method is OBC (`CommObc`) or Charter, nobody in `assigned_to`, status is not Completed or Removed, and the pickup date is today or later (or missing).

Click a tile to show just that set. Type chips, status chips, and the search box narrow the list further. Search checks the swap id, centers, method, times, status, crew, aircraft, phone, notes, airline, flight number, departure time, airport, terminal, and Airspace fields.

Commercial and OBC cards show a compact flight line: airline, flight number, departure airport and terminal, and departure time, for example `AA 1234 · JFK T8 · Dep 6:15 AM`. If those fields are empty the line reads `Flight TBD`.

OBC and Charter legs with nobody assigned are marked with an amber **Unassigned** line, including in history, unless the leg is Removed. Commercial, Ground, and Internal legs with nobody named are not flagged.

Edit writes `assigned_to`, `aircraft`, `phone`, `notes`, `airline`, `flight_number`, `departure_time`, `departure_airport`, and `departure_terminal`, and stamps `edited_by` / `edited_at`. The board refreshes about once a minute, and waits while an edit is open.

The NKR Dashboard has three tabs. The board is the default.

- **Board** — the dispatch cards described above. **Past dates** shows earlier pickup dates in the same card layout.
- **NKR Moves** — a week-by-week table of current and upcoming moves (Sunday–Saturday in `America/New_York`), with counts by type for the selected week and month-by-month totals. Monthly totals count Completed and Scheduled legs and omit Removed, unless you turn on **Show removed**. Type is shown as OBC, not CommObc. Flight and who is assigned appear as columns when they are known.
- **History** — completed moves, newest first, with Removed available through a status filter. Filter by month, type, and center, and search swap, flight, and names. Same columns as the NKR Moves table, including flight and who was assigned.

Direct links: `/nkr`, `/nkr#nkr`, and `/nkr#history`. The older `/#nkr` and `/#history` addresses redirect there.

## PF Dashboard

`/pf` is for trips that are not NKR moves: other organ work, air ambulance, and corporate. There is no ingest source yet. Any signed-in staff member can add, edit, or cancel a trip. Admins can delete one.

The board groups upcoming and active trips (Quote, Booked, In progress) by date, with filters for trip type and a search box. Tiles count trips today, the next three days, and open quotes. Commercial and OBC cards use the same flight line as NKR (`AA 1234 · JFK T8 · Dep 6:15 AM`).

**History** lists Completed and Cancelled trips, newest first, with search and filters by type and month, plus month-by-month totals by trip type.

The add/edit form fields are: trip type (Organ, Air Ambulance, Corporate), client/customer, trip date, from, to, pickup time, delivery/arrival time, mode (Charter, Commercial, OBC, Ground), operator/aircraft (tail), crew/assigned to, airline, flight number, departure time, departure airport, terminal, status (Quote, Booked, In progress, Completed, Cancelled), phone, and a free-text notes field (no PHI-specific field names). `created_by` / `created_at` and `edited_by` / `edited_at` are stamped automatically.

Export is `/api/trips.csv`.


## Auth

Staff create their own accounts at `/signup` (name, email, password, confirm). New accounts stay `pending` until an admin approves them, then they sign in at `/login` with email and password. Pending and disabled accounts cannot sign in. The first sign-up whose email matches `ADMIN_EMAIL` (case-insensitive) is activated as admin if no admin exists yet.

Admins use `/admin` to list accounts, approve, disable or re-enable, promote or demote, delete pending sign-ups, and create a one-time password-reset link (valid 7 days) to copy and send. `/setup?token=...` sets a new password from that link and cannot be reused.

`POST /api/admin/bootstrap` is authorized with `Authorization: Bearer $INGEST_TOKEN`. The JSON body is `{"email": "..."}`. If that user already exists, they are promoted to an active admin and the response is `{"ok": true, "email": "...", "role": "admin", "status": "active"}`. If not, the response is `404` `{"ok": false, "error": "not_found"}`. It does not create accounts or password-setup links.

`GET /login`, `GET /signup`, `GET /setup`, and `GET /healthz` are public. Everything else needs a session cookie. The cookie is `pf_session`, signed with the user id, HttpOnly, SameSite=Lax, and lasts 30 days. On Render it is Secure. Form posts also check the Origin or Referer against the same host. Edits are still stamped with the signed-in user's name.

Eight wrong login or sign-up attempts from the same address within ten minutes return 429.

`POST /logout` clears the cookie.

Ingest does not accept the session cookie. The read API does not accept the ingest token.

## API

Times and dates are strings. Empty columns are JSON `null`. The server never deletes a leg. A Removed leg is a status change.

Sending a key updates that column. Omitting a key leaves the column alone. A present `null` or blank string clears the column, with one exception: once `first_seen` is non-empty, ingest will not replace it or clear it.

A moves payload cannot change crew fields (`assigned_to`, `aircraft`, `phone`, `notes`) or Airspace fields. An Airspace payload cannot change logistics fields or crew fields. Airline, flight number, departure time, airport, and terminal are team-editable; both ingest endpoints may set them only when the stored value is empty, and never overwrite a value the team typed. On the Airspace endpoint only, `status` means the Airspace status text. If Airspace sends a combined flight string such as `AA 1234` or `AA1234` for a Commercial or OBC leg, and those fields are empty, the airline code and number are stored separately (the original string still goes in `airspace_flight`).

`swap_id` is required, at most 80 characters, and may not contain control characters. Other text is trimmed and truncated to a column cap (centers 120, notes 4000, driver names 200, the rest 40–80). A list of driver names is joined with `, `.

### `POST /api/ingest/moves`

`Authorization: Bearer $INGEST_TOKEN` and `Content-Type: application/json`.

Body is a JSON list, or an object with a list under `moves`, `legs`, `items`, `orders`, or `data`.

Accepted keys (CSV names, plus aliases):

| Key | Stored as |
| --- | --- |
| `swap_id` | `swap_id` |
| `pickup_date` | `pickup_date` (`YYYY-MM-DD`) |
| `donor`, `donor_center` | `donor` |
| `recipient`, `recipient_center` | `recipient` |
| `method` | `method` (stored as sent; `CommObc` stays `CommObc`) |
| `pickup`, `pickup_time` | `pickup` |
| `delivery`, `delivery_time` | `delivery` |
| `status` | `status` (`Scheduled`, `Completed`, `Removed`, or anything else) |
| `first_seen` | `first_seen` |
| `last_seen` | `last_seen` |
| `airline` | `airline` (filled only when empty) |
| `flight_number`, `flight` | `flight_number` (filled only when empty; combined strings like `AA 1234` are split) |
| `departure_time`, `etd`, `dep_time` | `departure_time` (filled only when empty) |
| `departure_airport`, `airport`, `origin_airport` | `departure_airport` (filled only when empty) |
| `departure_terminal`, `terminal` | `departure_terminal` (filled only when empty) |

```bash
curl -sS -X POST "$BASE/api/ingest/moves" \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{
    "swap_id": "11593/1/1",
    "pickup_date": "2026-11-24",
    "donor": "UMinn",
    "recipient": "Penn",
    "method": "CommObc",
    "pickup": "11/24 10:00 CST",
    "delivery": "11/24 18:15 EST",
    "status": "Scheduled",
    "first_seen": "2026-11-20",
    "last_seen": "2026-11-22"
  }]'
```

`200` body:

```json
{"ok": true, "inserted": 1, "updated": 0, "skipped": 0, "errors": []}
```

A bad row is skipped and listed: `{"index": 0, "error": "missing swap_id"}`. The rest of the batch is still saved. `errors` is also `swap_id too long`, `invalid swap_id`, or `expected an object`. The whole request is `400` `{"error": "expected a JSON list"}` when the body is not a list or one of those envelopes. Missing or wrong token is `401` `{"error": "unauthorized"}`.

### `POST /api/ingest/airspace`

Same auth, envelopes, and response shape. Upsert by `swap_id`. If the leg does not exist yet, a row is created with just the id and the Airspace columns.

| Key | Stored as |
| --- | --- |
| `swap_id` | `swap_id` |
| `airspace_order_id`, `order_id` | `airspace_order_id` |
| `airspace_driver`, `driver_names`, `drivers`, `driver_name`, `driver` | `airspace_driver` |
| `airspace_flight`, `flight_number`, `flight` | `airspace_flight`. For a Commercial or OBC leg, also fills `flight_number` (and `airline` when the string is like `AA 1234` or `AA1234`) if those columns are empty |
| `airline` | `airline` (filled only when empty) |
| `departure_time`, `etd`, `dep_time` | `departure_time` (filled only when empty) |
| `airport`, `departure_airport`, `origin_airport` | `departure_airport` (filled only when empty) |
| `terminal`, `departure_terminal` | `departure_terminal` (filled only when empty) |
| `airspace_awb`, `awb` | `airspace_awb` |
| `airspace_status`, `status` | `airspace_status` |

```bash
curl -sS -X POST "$BASE/api/ingest/airspace" \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{
    "swap_id": "11593/1/1",
    "order_id": "AS-100",
    "driver_names": ["Sam Ruiz", "Jo Park"],
    "flight_number": "DL 1842",
    "awb": "001-12345678",
    "airspace_status": "Tendered"
  }]'
```

### `GET /api/moves`

Session cookie. Returns every leg.

```json
{
  "timezone": "America/New_York",
  "today": "2026-11-23",
  "moves": [
    {
      "swap_id": "11593/1/1",
      "pickup_date": "2026-11-24",
      "donor": "UMinn",
      "recipient": "Penn",
      "method": "CommObc",
      "pickup": "11/24 10:00 CST",
      "delivery": "11/24 18:15 EST",
      "status": "Scheduled",
      "first_seen": "2026-11-20",
      "last_seen": "2026-11-22",
      "airline": "DL",
      "flight_number": "1842",
      "departure_time": "2026-11-24T06:15",
      "departure_airport": "MSP",
      "departure_terminal": "1",
      "airspace_order_id": "AS-100",
      "airspace_driver": "Sam Ruiz, Jo Park",
      "airspace_flight": "DL 1842",
      "airspace_awb": "001-12345678",
      "airspace_status": "Tendered",
      "assigned_to": "Alex Rivera",
      "aircraft": null,
      "phone": "555-0100",
      "notes": "Wheels up 10:15",
      "edited_by": "Alex",
      "edited_at": "2026-11-23T06:12:04Z"
    }
  ]
}
```

Order is `pickup_date`, then `swap_id`. Missing dates sort last. `401` when the session is missing.

### `PATCH /api/moves`

Session cookie. JSON object. `swap_id` plus at least one of `assigned_to`, `aircraft` (`tail` and `aircraft_tail` are aliases), `phone` (`contact`, `phone_contact`), `notes`, `airline`, `flight_number` (`flight` is an alias), `departure_time` (`etd`, `dep_time`), `departure_airport` (`airport`, `origin_airport`), `departure_terminal` (`terminal`). Blank clears a field. Sets `edited_by` from the login name and `edited_at` to UTC `YYYY-MM-DDTHH:MM:SSZ`.

```bash
curl -sS -X PATCH "$BASE/api/moves" \
  -H "Content-Type: application/json" \
  --cookie "pf_session=..." \
  -d '{"swap_id":"11593/1/1","assigned_to":"Alex Rivera","aircraft":"N552PF","phone":"555-0100","notes":"Wheels up 10:15"}'
```

`200` `{"ok": true, "move": { ...same shape as one element of moves... }}`. `400` `{"error": "missing swap_id"}` or `{"error": "no team fields"}` or `{"error": "expected a JSON object"}`. `404` `{"error": "unknown swap_id"}`.

### `GET /api/moves.csv`

Session cookie. All legs, same columns as the JSON object, header row, UTF-8 with BOM. `Content-Disposition: attachment; filename="moves.csv"`. Cells that start with `=`, `+`, `-`, or `@` are prefixed with a quote.

### `GET /api/trips`

Session cookie. `{"timezone":"America/New_York","today":"YYYY-MM-DD","trips":[...],"months":[...]}`. Each trip includes `id`, `trip_type`, `client`, `trip_date`, `origin`, `destination`, `pickup_time`, `delivery_time`, `mode`, `operator_aircraft`, `assigned_to`, `airline`, `flight_number`, `departure_time`, `departure_airport`, `departure_terminal`, `status`, `phone`, `notes`, `created_by`, `created_at`, `edited_by`, and `edited_at`. `months` are calendar-month totals by trip type for dated trips.

### `POST /api/trips`

Session cookie. JSON object. `trip_type` is required (`Organ`, `Air Ambulance`, or `Corporate`). Status defaults to `Quote`. `mode` if set must be `Charter`, `Commercial`, `OBC`, or `Ground`. `status` if set must be `Quote`, `Booked`, `In progress`, `Completed`, or `Cancelled`. `trip_date` if set must be `YYYY-MM-DD`.

`201` `{"ok": true, "trip": { ... }}`. `400` `{"error": "..."}`.

### `PATCH /api/trips/<id>`

Session cookie. Partial update of the same fields. Used to edit or to cancel (`{"status":"Cancelled"}`).

`200` `{"ok": true, "trip": { ... }}`. `404` `{"error": "unknown trip"}`.

### `DELETE /api/trips/<id>`

Session cookie, admin only. Permanently deletes the trip. `200` `{"ok": true}`. `403` `{"error": "forbidden"}`. `404` `{"error": "unknown trip"}`.

### `GET /api/trips.csv`

Session cookie. All trips, same columns as the JSON object, header row, UTF-8 with BOM. `Content-Disposition: attachment; filename="pf-trips.csv"`. Cells that start with `=`, `+`, `-`, or `@` are prefixed with a quote.

### `GET /healthz`

No auth. `200` body `ok\n` when the database answers `SELECT 1`. `503` body `db unavailable\n` when it does not. Render's health check uses this path.

## Deploy on Render

`render.yaml` is the Blueprint. It matches the other ParaFlight apps: Python, `pip install -r requirements.txt`, `python3 server.py`, region `virginia`.

- Web service `pf-dashboard`, plan `starter` (legacy name for 0.5 CPU / 512 MB, still accepted by the current Blueprint schema), health check `/healthz`, branch `main`.
- Postgres `pf-dashboard-db`, plan `free`, PostgreSQL 16, database `pf_dashboard`, user `pf_dashboard_user`, public IP allow list empty.

Free Postgres expires 30 days after it is created, and backups go with it. Before that day, change the database `plan` to `basic-256mb` (the current id for that size is `0.1c-256mb`; both are in the schema) and sync the Blueprint, or change the plan in the Dashboard. `databaseName`, `user`, `region`, and `postgresMajorVersion` cannot be changed later.

After this file is on `main`:

1. Open https://dashboard.render.com/blueprint/new?repo=https://github.com/urgentflights/pf-dashboard
2. Set `TEAM_PASSWORD` when prompted (kept only as a disabled fallback). Set `ADMIN_EMAIL` to the first admin's email. Render fills `INGEST_TOKEN` and `SECRET_KEY`.
3. Apply, then copy `INGEST_TOKEN` from the service Environment tab for the automation.

The service does not spin down on the starter plan. The filesystem is ephemeral; the SQLite fallback is only for local runs.

## Custom domain later

Custom domains are for the web service, after it is live. TLS is issued and renewed for you. You do not terminate TLS in the app.

1. Dashboard → **pf-dashboard** → **Settings** → **Custom Domains** → **Add Custom Domain**.
2. For a subdomain such as `moves.example.com`, add a CNAME at your DNS host. Name `moves`, target the service hostname shown in the Dashboard (`pf-dashboard.onrender.com`, or the exact value Render prints).
3. For an apex name (`example.com`), use your DNS host's ALIAS, ANAME, or flattened CNAME. Where those are not available, use the A record and IP Render shows on the domain page.
4. Remove any AAAA records for that name. Render is IPv4.
5. Click **Verify**. If it fails, wait a few minutes and flush the resolver cache, then verify again. The certificate follows verification.
6. If the zone has CAA records, allow `letsencrypt.org` and `pki.goog`, including `issuewild` if you use a wildcard.

To declare the hostname in the Blueprint as well, add a `domains` list on the web service (`domains: [moves.example.com]`). That only records the name. DNS is still configured at the registrar. After at least one custom domain works, the `onrender.com` hostname can be turned off under **Render Subdomain** on the same settings page.
