# EnterpriseAI — Auth Service (uv project root)

Universal, standalone authentication service. Implements the 3-tier auth model
(**Vendor**, **Tenant**, **Workspace**) with **Single Sign-On (SSO / OIDC)**
support.

The monorepo root **is** the `uv` project. All project/package configuration
(`pyproject.toml`, `uv.lock`, `.env`, `alembic.ini`, `README.md`) lives here;
`apps/auth/` contains only source code (`src/`, `alembic/`, `tests/`).

## Tech Stack

| Concern       | Technology                                            |
| :------------ | :---------------------------------------------------- |
| Package mgr   | `uv`                                                  |
| Web framework | FastAPI (Pydantic v2)                                 |
| DB/ORM        | SQLAlchemy 2.0 (async) + `asyncpg` / `aiosqlite`      |
| Migrations    | Alembic                                              |
| Password      | `pwdlib[argon2]` (Argon2id)                           |
| Tokens        | `PyJWT[crypto]` (RS256 + JWKS)                        |
| SSO client    | `httpx`                                               |
| CSRF          | `itsdangerous`                                        |
| Config        | `pydantic-settings` (`config.py` = global settings)   |

## Configuration — `.env` / `.env.example`

All configuration is centralized in the **global settings** object defined in
`apps/auth/src/config.py` (`Settings` model + `get_settings()`). Every module
in the project imports this single global instance, so changing an environment
variable in `.env` automatically propagates across the whole service.

```bash
cp .env.example .env   # then edit values
```

- `.env` → real, secret values. **Git-ignored.**
- `.env.example` → committed template for anyone to copy.

`pydantic-settings` gives OS environment variables priority over the `.env`
file, and every variable maps directly to a field on the global `Settings`.

## Quickstart

```bash
uv sync                        # create .venv + install locked deps
cd apps/auth && uv run uvicorn src.main:app --reload --port 8001
```

or from the root:

```bash
uv run uvicorn src.main:app --app-dir apps/auth --reload --port 8001
```

Open docs at <http://localhost:8001/docs> and JWKS at
<http://localhost:8001/.well-known/jwks.json>.

## Database migrations

```bash
uv run alembic upgrade head     # alembic.ini lives at the root
```

## Tests

```bash
uv run pytest -q
uv run pytest -q -k security   # focus on JWT/JWKS/hashing
```

## Endpoints (`/api/v1`)

| Method | Path                      | Description                      |
| :----- | :------------------------ | :------------------------------- |
| POST   | `/auth/register`          | Local registration               |
| POST   | `/auth/login`             | Local login (issues JWTs)        |
| POST   | `/auth/refresh`           | Rotate refresh token             |
| POST   | `/auth/logout`            | Revoke session                   |
| GET    | `/auth/me`                | Current user + SSO provider info |
| GET    | `/sso/initiate`           | Begin OIDC/PKCE login flow       |
| GET    | `/sso/callback`           | OIDC callback (issues JWTs)      |
| POST   | `/tenant`                 | Create tenant (admin)            |
| GET    | `/.well-known/jwks.json`  | Public RSA public keys (RS256)   |

## Project layout

```
EnterpriseAI/                 # uv project root
├── .env, .env.example        # global env config (secrets git-ignored)
├── .gitignore, .python-version
├── pyproject.toml, uv.lock   # uv project & dependencies
├── alembic.ini               # migration config (points at apps/auth/alembic)
├── auth.db                   # local SQLite database (git-ignored)
├── README.md
└── apps/auth/                # auth service source ONLY
    ├── alembic/              # migration scripts
    ├── tests/                # pytest suite
    ├── .keys/                # generated RSA keypair (git-ignored)
    └── src/                  # application source code
        ├── main.py           # FastAPI app + JWKS/health endpoints
        ├── config.py         # GLOBAL settings (used everywhere)
        ├── core/             # security.py, oidc.py
        ├── db/               # base.py, session.py, rls.py
        ├── models/           # user, tenant, workspace, auth
        └── api/v1/           # auth, sso, tenant routers
```

## Docker

Both services containerize; one command runs the whole stack:

```bash
docker compose up --build -d
```

| Service | URL | Notes |
| :------ | :-- | :---- |
| web | http://localhost:3000/auth | Next.js standalone runner (image ~74 MB) |
| auth | http://localhost:8001/docs | FastAPI + Uvicorn |

The auth container's entrypoint runs **`alembic upgrade head` before starting**
uvicorn, so a fresh deployment migrates itself. SQLite lives on the
`auth-data` volume and the RSA keypair on `auth-keys`, so data and tokens
survive restarts.

Useful commands:

```bash
docker compose ps                # status (auth shows "healthy")
docker compose logs -f auth      # entrypoint + request logs
docker compose down              # stop (keeps volumes)
docker compose down -v           # stop AND wipe database/keys
```

### Switching to PostgreSQL

The compose file ships an optional Postgres service behind the `postgres`
profile:

```bash
docker compose --profile postgres up --build -d
```

Then under `services.auth.environment` set:

```yaml
DATABASE_URL: postgresql+asyncpg://auth:auth@db:5432/auth
```

and remove the `DATABASE_URL` line that points at SQLite. Migrations apply
automatically on boot.

### Configuration in containers

All settings come from environment variables (see `.env.example`) — override
them per-service under `environment:` in `docker-compose.yml`. The frontend's
`NEXT_PUBLIC_API_URL` is inlined at **build** time; pass
`--build-arg NEXT_PUBLIC_API_URL=...` (already wired through compose) and use
a host-reachable URL, since API calls happen from the browser.

---

## Fresh machine? (`git clone` → running)

Nothing is committed that shouldn't be (no DB, no `.env`, no RSA keys), so a
new system needs exactly three steps:

```bash
cp .env.example .env        # 1. create your local env file (defaults work)
make install                # 2. uv sync + pnpm install (lockfiles pinned)
make dev                    # 3. run API :8001 + Web :3000 together
```

**Tables are created automatically.** On startup the API runs Alembic to bring
the schema to `head` against whatever `DATABASE_URL` points at — you'll see
`[auth] database schema is up to date (alembic=head)` in the logs. It's tracked
in the `alembic_version` table, so later `make upgrade` calls are safe no-ops.

> Older hand-made SQLite files (created before migrations existed) can be
> aligned once with `make stamp`; then normal upgrades continue from there.

### Make targets

| Command | What it does |
| :------ | :----------- |
| `make install` | backend (`uv sync --frozen`) + frontend (`pnpm install --frozen-lockfile`) |
| `make dev` | API + Web with hot reload, one command |
| `make upgrade` / `make downgrade` | migrate forward / back one step |
| `make revision m="add x"` | autogenerate a new migration |
| `make test` | pytest + vitest |
| `make docker-up` | same stack inside Docker |

---

## Switching databases (SQLite → Postgres → …)

Native — **one env var**, zero code changes:

```bash
# .env
DATABASE_URL=postgresql+asyncpg://auth:auth@localhost:5432/auth
```

then start the API (or run `make upgrade`). The *same* migration chain builds
and tracks the schema on the new engine; drivers `asyncpg` (PG) and `aiosqlite`
(SQLite) are both already installed. Everything else — models, RLS helpers,
tokens — is dialect-agnostic (`src/db/rls.py` no-ops tenant GUCs on SQLite).

Docker users: uncomment the `DATABASE_URL` postgres line under
`services.auth.environment`, bring up the bundled `db` service
(`docker compose --profile postgres up -d`), done.
