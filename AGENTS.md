# AGENTS.md

## Cursor Cloud specific instructions

### Overview
Neuro-Seller is a Python FastAPI backend for an AI-powered sales agent creation platform. The frontend is hosted externally on Base44 (not in this repo). This repo contains only the backend service.

### Services
| Service | How to run | Notes |
|---------|-----------|-------|
| **FastAPI backend** | `cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload` | Requires env vars below |
| **PostgreSQL** | `sudo pg_ctlcluster 16 main start` | Must be running before backend starts |

### Required environment variables
Set these in `backend/.env` (loaded via `python-dotenv`):
- `DATABASE_URL` — PostgreSQL connection string (e.g. `postgresql://neuroseller:neuroseller@localhost:5432/neuroseller`)
- `OPENAI_API_KEY` — Required for AI chat features; use a placeholder for non-AI endpoint testing
- `SECRET_KEY` — App secret key
- `ENVIRONMENT=development` and `DEBUG=True` — Enables Swagger docs at `/docs`

### Database setup gotchas
- The Alembic migrations assume base tables already exist (they add columns, not create tables). On a fresh DB, run `python3 -c "from app.core.database import Base, engine; from app.models import *; Base.metadata.create_all(bind=engine)"` from `backend/` first, then `alembic stamp head` to mark all migrations as applied.
- On subsequent runs, `alembic upgrade head` works normally since tables exist.

### Lint & tests
- No test framework or linter is preconfigured in the repository.
- `flake8 --max-line-length=120 app/ main.py` can be used for basic linting (install via `pip install flake8`).
- The codebase has many pre-existing whitespace warnings (W291/W293) which are not blocking.

### PATH note
User-installed pip binaries are in `~/.local/bin`. This is added to PATH in `~/.bashrc`.
