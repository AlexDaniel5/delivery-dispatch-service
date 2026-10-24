# Delivery Dispatch Service

A courier order-dispatch REST API built with **FastAPI**, **SQLAlchemy**, and
**WebSockets**. It assigns incoming delivery orders to the nearest available
courier, queues orders when everyone is busy, streams status changes to clients
in real time, and exposes Prometheus metrics.

---

## Features

| Capability | Where |
|---|---|
| Nearest-courier assignment (haversine distance + ETA) within a configurable radius | [`app/dispatch.py`](app/dispatch.py), [`app/geo.py`](app/geo.py) |
| Queue orders when no courier is available; assign automatically when one frees up | [`app/dispatch.py`](app/dispatch.py) |
| Order lifecycle as an explicit state machine that rejects invalid transitions | [`app/state_machine.py`](app/state_machine.py) |
| Idempotency keys so a retried `POST /orders` never creates a duplicate | [`app/dispatch.py`](app/dispatch.py) |
| No double-assignment, via a conditional `UPDATE` inside a single transaction | [`app/dispatch.py`](app/dispatch.py) |
| WebSocket streaming of order status changes | [`app/main.py`](app/main.py), [`app/events.py`](app/events.py) |
| Structured JSON request logging with a per-request request ID | [`app/logging_config.py`](app/logging_config.py) |
| Prometheus metrics (dispatch latency, orders-by-status) | [`app/metrics.py`](app/metrics.py) |

---

## Design

### Order lifecycle (state machine)

```
            ┌─────────┐   no courier    ┌────────┐
 POST ────▶ │ PENDING │ ───────────────▶│ QUEUED │
            └────┬────┘                 └───┬────┘
                 │ courier found            │ courier frees up
                 ▼                          │
            ┌──────────┐ ◀──────────────────┘
            │ ASSIGNED │
            └────┬─────┘
                 ▼
          ┌────────────┐        ┌───────────┐
          │ PICKED_UP  │ ─────▶ │ DELIVERED │   (terminal)
          └────────────┘        └───────────┘

 Any non-terminal state ─────▶ CANCELLED            (terminal)
```

Every transition goes through `DispatchService.transition`, the single place an
order's status changes. It validates the move against `ALLOWED_TRANSITIONS`,
raising `InvalidTransitionError` (surfaced as HTTP `409`) for anything illegal —
e.g. `assigned → delivered` or any transition out of a terminal state. Terminal
transitions (`delivered`/`cancelled`) free the assigned courier and drain the
queue.

### Assignment & the no-double-assignment guarantee

`try_assign` finds the nearest `available` courier within
`assignment_radius_km` (great-circle distance from the courier to the order's
**pickup** point) and claims it with a conditional update:

```sql
UPDATE couriers
   SET status = 'busy', current_order_id = :order_id
 WHERE id = :courier_id
   AND status = 'available';   -- guard
```

The claim only succeeds if `rowcount == 1`. If two dispatchers race for the same
courier, exactly one update matches; the loser rolls back, re-reads, and retries
with the next-nearest courier (or queues the order). This makes
double-assignment impossible without table-level locking. ETA is a simple
`distance / courier_speed_kmh` estimate.

### Queueing

If no courier is eligible, the order transitions to `QUEUED`. Whenever a courier
becomes available — a new registration, or an existing courier completing a
delivery — `process_queue` assigns queued orders oldest-first (FIFO by
`created_at`) until it runs out of orders or couriers.

### Idempotency

`POST /orders` accepts an optional `Idempotency-Key` header. The key is stored
on the order under a `UNIQUE` constraint. A repeat with the same key returns the
original order (HTTP `200`) instead of creating a new one (HTTP `201`).
Concurrent requests with the same key are made safe by catching the
`IntegrityError` from the unique constraint and returning the winner's order.

### Real-time updates

An in-process `EventBus` fans out status-change events to subscribers. HTTP
handlers run in FastAPI's threadpool, so the bus publishes to the asyncio loop
with `loop.call_soon_threadsafe`; WebSocket handlers (`/ws/orders`) consume from
a per-connection `asyncio.Queue` and forward events as JSON.

### Observability

- **Logging** — one JSON line per request (`app/logging_config.py`), carrying a
  `request_id` taken from the `X-Request-ID` header or generated per request and
  echoed back in the response. Domain events (`order transition`,
  `order assigned`) are logged with structured fields.
- **Metrics** — `GET /metrics` exposes a `dispatch_latency_seconds` histogram,
  an `orders_by_status` gauge (recomputed from the database on every change),
  and `orders_created_total` / `assignments_total` counters.

---

## Running it

Requires **Python 3.11+**.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"      # or: pip install -r requirements.txt

uvicorn app.main:app --reload
```

The API is then at `http://127.0.0.1:8000`; interactive docs at `/docs`.

### With Docker + Postgres

The app is database-agnostic; `docker-compose.yml` runs it against Postgres:

```bash
docker compose up --build
```

This starts Postgres (with a healthcheck) and the API on
`http://localhost:8000`, wired together via
`DISPATCH_DATABASE_URL=postgresql+psycopg://dispatch:dispatch@db:5432/dispatch`.
Tables are created on startup. To run the image standalone against your own
Postgres:

```bash
docker build -t delivery-dispatch .
docker run -p 8000:8000 \
  -e DISPATCH_DATABASE_URL="postgresql+psycopg://user:pass@host:5432/dbname" \
  delivery-dispatch
```

> The conditional-`UPDATE` assignment guarantee and the idempotency unique
> constraint are standard SQL and behave identically on SQLite and Postgres.
> Schema is created with `create_all` on startup; a production setup would
> front this with Alembic migrations.

### Configuration

Configuration is via environment variables (prefix `DISPATCH_`):

| Variable | Default | Meaning |
|---|---|---|
| `DISPATCH_DATABASE_URL` | `sqlite:///./dispatch.db` | SQLAlchemy database URL |
| `DISPATCH_ASSIGNMENT_RADIUS_KM` | `10.0` | Max courier→pickup distance for eligibility |
| `DISPATCH_COURIER_SPEED_KMH` | `30.0` | Assumed speed used for the ETA estimate |
| `DISPATCH_REQUEST_LOGGING` | `true` | Emit a JSON log line per request |
| `DISPATCH_AUTO_CREATE_TABLES` | `true` | Create tables on startup; set `false` and use Alembic in production |
| `DISPATCH_API_KEYS` | `""` | Comma-separated API keys; empty disables auth |

### Authentication

Write endpoints (`POST /couriers`, `PATCH /couriers/{id}`, `POST /orders`,
`POST /orders/{id}/status`) accept an optional `X-API-Key` header. Auth is
**opt-in**: with `DISPATCH_API_KEYS` empty (the default) every request is
allowed; set it (e.g. `DISPATCH_API_KEYS=key-a,key-b`) to require a matching key
on writes. Reads, `/health`, and `/metrics` stay open.

```bash
curl -X POST localhost:8000/couriers -H 'X-API-Key: key-a' \
  -H 'content-type: application/json' -d '{"name":"Alice","lat":0,"lon":0}'
```

### Database migrations (Alembic)

Schema is managed by Alembic (`migrations/`), with the environment reading the
same `DISPATCH_DATABASE_URL` and ORM metadata as the app:

```bash
alembic upgrade head     # apply migrations
alembic downgrade -1     # roll back one
alembic revision --autogenerate -m "describe change"   # after editing models
alembic check            # fail if models and migrations have drifted
```

The Docker `app` service runs `alembic upgrade head` before starting and has
`DISPATCH_AUTO_CREATE_TABLES=false`, so Postgres is migrated rather than
auto-created. Locally, the default `create_all`-on-startup keeps things simple.

---

## Example requests

Register a courier:

```bash
curl -s -X POST localhost:8000/couriers \
  -H 'content-type: application/json' \
  -d '{"name": "Alice", "lat": 37.7749, "lon": -122.4194}'
```

Create an order (assigned if a courier is in range, otherwise queued):

```bash
curl -s -X POST localhost:8000/orders \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: order-abc-123' \
  -d '{"pickup_lat": 37.7750, "pickup_lon": -122.4190,
       "dropoff_lat": 37.8044, "dropoff_lon": -122.2712}'
```

```json
{
  "id": "…",
  "status": "assigned",
  "courier_id": "…",
  "distance_km": 0.05,
  "eta_minutes": 0.1,
  "...": "..."
}
```

Advance the lifecycle:

```bash
curl -s -X POST localhost:8000/orders/<order_id>/status \
  -H 'content-type: application/json' -d '{"status": "picked_up"}'
curl -s -X POST localhost:8000/orders/<order_id>/status \
  -H 'content-type: application/json' -d '{"status": "delivered"}'
```

An illegal transition returns `409`:

```bash
# assigned -> delivered is not allowed
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  localhost:8000/orders/<order_id>/status \
  -H 'content-type: application/json' -d '{"status": "delivered"}'
# 409
```

Stream status changes over WebSocket:

```bash
# e.g. with `websocat`
websocat ws://localhost:8000/ws/orders
# {"type": "order_status", "order_id": "…", "status": "assigned", ...}
```

Scrape metrics:

```bash
curl -s localhost:8000/metrics | grep -E 'dispatch_latency|orders_by_status'
```

### API summary

| Method & path | Description |
|---|---|
| `GET /` | Service index |
| `GET /health` | Liveness probe |
| `POST /couriers` 🔑 | Register a courier (drains the queue) |
| `GET /couriers` | List couriers (filter by `status`; `limit`/`offset`) |
| `GET /couriers/{id}` | Fetch a courier |
| `PATCH /couriers/{id}` 🔑 | Update a courier's location and/or availability |
| `POST /orders` 🔑 | Create & dispatch an order (`Idempotency-Key` optional) |
| `GET /orders` | List orders (filter by `status`/`courier_id`; `limit`/`offset`) |
| `GET /orders/{id}` | Fetch an order |
| `POST /orders/{id}/status` 🔑 | Advance an order's status |
| `WS /ws/orders` | Stream order status-change events |
| `GET /metrics` | Prometheus metrics |

🔑 = requires `X-API-Key` when `DISPATCH_API_KEYS` is set.

---

## Development

```bash
ruff check .          # lint
ruff format --check . # formatting
mypy app              # strict type checking
pytest -q             # 100+ tests
```

The test suite covers the state machine, idempotency (including a concurrent
same-key race), the no-double-assignment guarantee (including concurrent
dispatch against a single courier), queueing, the event bus, metrics, and the
HTTP + WebSocket API.

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs ruff, `ruff format
--check`, strict mypy, and the test suite on Python 3.11, 3.12, and 3.13 for
every push and pull request.

## Project layout

```
app/
  config.py          # settings (env-driven)
  auth.py            # API-key dependency for write endpoints
  database.py        # engine / session management
  models.py          # SQLAlchemy ORM models
  schemas.py         # Pydantic request/response models
  state_machine.py   # order lifecycle + allowed transitions
  geo.py             # haversine distance + ETA
  dispatch.py        # assignment, queueing, transitions (core logic)
  events.py          # in-process pub/sub event bus
  metrics.py         # Prometheus metrics
  logging_config.py  # structured JSON logging + request ID
  main.py            # FastAPI app: routes, middleware, WebSocket
migrations/          # Alembic environment + versioned migrations
tests/               # pytest suite
Dockerfile
docker-compose.yml   # app + Postgres
```
