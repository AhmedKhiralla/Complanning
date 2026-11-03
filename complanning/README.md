# Complanning

Production planning for pharmaceutical and other manufacturing companies, by **Comp11 Labs**.

This is **Phase 1 – Foundation**: companies (tenants), sites, users and per-site roles, company settings
(feature toggles, terminology, password and session policy), and a database-enforced audit trail.
The web app is English and Arabic (right-to-left), with light, dark and system themes.

## How it is built

| Part | Technology |
| --- | --- |
| Web app | React 19 + TypeScript, bundled with esbuild (`frontend/`) |
| API | Python 3.13, Starlette, pydantic, raw SQL through psycopg 3 (`backend/app/`) |
| Database | PostgreSQL 16, UTF-8 (`backend/migrations/*.sql`) |
| Hosting | One Docker image on Railway: the API serves the web app too |

### Security model (21 CFR Part 11 controls)

- **Tenant isolation in the database.** Every request runs as the restricted role `cp_app` with row-level
  security. A company's queries can only ever return that company's rows, even if application code has a bug.
- **Audit trail written by the database.** Triggers record every insert, change and removal with the user,
  server time, and old and new values per field. Sign-ins, failed sign-ins, lockouts, password changes and
  exports are recorded too. The application can only read the audit table; updates, deletes and truncation
  are rejected by a guard trigger. Password hashes are never copied into the audit trail.
- **Accounts.** Unique users, scrypt password hashing, configurable password policy (length, character
  classes, expiry, history), lockout after failed attempts, sign-out after inactivity, forced change of
  one-time passwords, sessions revoked on password reset or when a user is disabled.
- **Web.** HttpOnly + Secure + SameSite=Strict session cookie, a required application header on every
  change (CSRF protection), strict Content-Security-Policy and other security headers.

## Deploy on Railway

You need the PostgreSQL database already created in your Railway project.

1. **Put the code on GitHub.** Create an empty private repository and push this folder to it:
   ```bash
   git remote add origin https://github.com/<you>/complanning.git
   git push -u origin main
   ```
2. **Add the app service.** In the same Railway project as Postgres, click **+ New → GitHub Repo** and pick
   the repository. Railway finds `railway.json` and builds the `Dockerfile`.
3. **Set the variables** on the new service (**Variables** tab):

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference to the Postgres service) |
   | `PLATFORM_ADMIN_EMAIL` | your platform administrator email |
   | `PLATFORM_ADMIN_PASSWORD` | a first password: 10+ characters with upper, lower, number and symbol |
   | `PLATFORM_ADMIN_NAME` | `Comp11 Labs` (optional) |

4. **Give it a web address.** Service **Settings → Networking → Generate Domain**.
5. **Sign in** at that address with the platform administrator email and password. You are asked to choose
   a new password straight away. After that, delete `PLATFORM_ADMIN_PASSWORD` from the variables; it is only
   used once, to create the first administrator when none exists.
6. **Create a company** under **Companies**. Copy the one-time password shown for its administrator and
   share it securely. That person signs in, sets their own password, and adds sites and users.

On every start the app applies new database migrations automatically (with a lock, so two instances never
migrate at once). The database must be UTF-8, which is Railway's default.

## Run locally

Requirements: Python 3.12+, Node 20+, PostgreSQL 14+ (UTF-8).

```bash
# 1. Database
createdb complanning

# 2. Web app
cd frontend
npm install
npm run build          # or: npm run dev   (rebuilds on change)

# 3. API (serves the web app from frontend/dist)
cd ../backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://postgres@127.0.0.1:5432/complanning COOKIE_SECURE=false \
       PLATFORM_ADMIN_EMAIL=you@example.com PLATFORM_ADMIN_PASSWORD='Change#Me2026'
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000.

### Tests

End-to-end tests create a fresh database, start a real server and check tenant isolation (through the API
and with raw SQL), append-only audit, old/new values, lockout, password policy and history, forced password
change, session revocation and export logging.

```bash
cd backend
export TEST_DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1:5432/postgres
pytest -q
```

## Project layout

```
backend/
  app/
    api.py            request handling: auth, roles, validation, transactions, errors
    db.py             connection pool and per-request security context
    security.py       password hashing, policy, session tokens
    defaults.py       feature toggles and renamable terms
    migrate.py        migration runner and first-administrator bootstrap
    main.py           routes, security headers, web app serving
    routers/          auth, platform (companies), company (sites, users, settings), audit_trail
  migrations/         numbered SQL files, applied in order
  tests/              end-to-end tests
frontend/
  src/
    lib/              API client, router, theme, translations (strings.ts), session
    components/       shell, shared UI
    pages/            sign-in, home, companies, sites, users, settings, audit trail
  public/brand/       Comp11 Labs logo (light and dark), favicon
```

## Next phase

Phase 2 – Master data: units and conversions, items and materials, markets and price history,
bills of materials with versions, machines and routings with the drag-and-drop flow editor, calendars.
See the specification document for the full plan.
