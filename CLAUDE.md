# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**devs-manager** (ранее DCO / Dev Cost Optimizer) — дипломный проект, цель которого — анализ эффективности разработчиков на основе метрик из коммитов и других сущностей различных VCS (GitHub, GitLab, Bitbucket, SVN).

Проект состоит из двух репозиториев:
- **devs-manager** (`/home/czar/devs-manager/`) — бэкенд (FastAPI)
- **devs-manager-app** (`/home/czar/devs-manager-app/`) — фронтенд (Next.js)

---

## Backend — devs-manager

**Stack:** Python 3.13, FastAPI, SQLAlchemy, PostgreSQL 16, Alembic, Docker

### Commands

```bash
# Development (auto-reload)
python3.13 -m uvicorn src.api.main:app --reload

# Docker
docker-compose up        # foreground
docker-compose up -d     # detached

# Database migrations
alembic revision --autogenerate -m "description"   # create
alembic upgrade head                                # apply
alembic downgrade -1                                # rollback
```

No test or lint commands configured yet. The `/test` directory exists but is empty.

### Architecture

Layered architecture with adapter pattern:

```
src/
├── api/            # FastAPI routes, Pydantic schemas, dependency injection
│   ├── main.py     # App entry point (FastAPI instance, route registration)
│   ├── routes/     # Endpoint handlers
│   ├── schemas/    # Request/response Pydantic models
│   └── dependencies.py  # JWT auth + DB session injection
├── services/       # Business logic
│   ├── external/   # GitHub API client (github_stats_manual.py)
│   └── internal/   # Core processing pipeline
│       ├── process.py           # Main commit processing orchestrator
│       └── preprocessing/       # Commit enrichment pipeline steps
├── adapters/db/    # Database layer
│   ├── base.py     # SQLAlchemy engine & session config
│   ├── models/     # ORM models (*Model suffix)
│   └── repositories/  # Data access (generic BaseRepository<T>)
├── data/           # Domain models, enums, GitHub API DTOs
│   ├── domain/     # Business entities (Commit, FileChange, Analysis)
│   ├── enums/      # Type enums (commit types, languages, roles, VCS providers)
│   └── github_api_response/  # GitHub API response DTOs
├── core/           # App config (Pydantic Settings) and security (JWT, encryption)
└── util/           # Logger, mappers
```

### Key Processing Pipeline

`src/services/internal/process.py` → `process_repo()`:

1. Fetch commits from GitHub API (paginated)
2. Create/retrieve repository and contributors in DB
3. Deduplicate commits by SHA
4. Enrichment pipeline: file filtering → language detection → commit type classification → metadata extraction (conventional commits, merge/revert detection, breaking changes)
5. Persist commits and file-level statistics

### Naming Conventions

- ORM models: `*Model` (e.g., `UserModel`, `RepositoryModel`)
- Repositories: `*Repository` with generic `BaseRepository<T>` base class
- Services: `*Service`
- Domain models: plain names (`Commit`, `FileChange`)

### Auth & Security

- JWT auth (python-jose), 12-hour expiration, injected via FastAPI dependencies
- GitHub tokens encrypted at rest with Fernet symmetric encryption
- Auth header: `Authorization: Bearer <token>`
- Custom headers: `ght` (GitHub token), `acc-scope` (account scope as `username:id`)

### Environment Variables

Required in `.env` (see `.env_example`):
- `SECRET_KEY` — JWT signing key (`openssl rand -hex 128`)
- `ENCRYPTION_KEY` — Fernet key for GitHub token encryption
- `GITHUB_TOKEN` — default GitHub API token
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` — PostgreSQL connection

### Commit Classification

Rule-based `HeuristicCommitClassifier` using keyword matching. Conventional commit regex: `^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([a-z0-9-]+\))?: .+$`. Configuration in `analysis_settings_template.json`.

### Language Detection

Extension-based mapping in `src/services/internal/preprocessing/lang_detector.py`. ML model disabled (poor accuracy on short snippets). Patterns defined in `src/data/enums/language.py`.

---

## Frontend — devs-manager-app

**Stack:** Next.js 16, React 19, TypeScript 5, Tailwind CSS 4

### Commands

```bash
npm run dev      # dev server
npm run build    # production build
npm start        # production server
npm run lint     # ESLint
```

No test runner configured yet.

### Architecture

Next.js App Router с файловой маршрутизацией:

```
app/
├── layout.tsx              # Root layout (server component)
├── page.tsx                # Home — API Testing Dashboard
├── globals.css             # Global styles (Tailwind)
├── registration/
│   └── page.tsx            # Multi-step registration (info → email verification → VCS setup)
├── setup/
│   └── page.tsx            # Organization setup wizard (company size → sprint config → teams → repos)
├── main/
│   └── page.tsx            # Main dashboard
└── api/                    # Next.js API routes — proxy to backend (localhost:8000)
    ├── register/route.ts
    ├── send-verification/route.ts
    ├── verify-email/route.ts
    ├── setup-vcs/route.ts
    └── check-availability/route.ts
```

### Key Patterns

- All pages are client components (`"use client"`)
- State management: `useState` (no global store)
- API calls go through Next.js API routes, which proxy to the FastAPI backend at `http://localhost:8000`
- Styling: Tailwind CSS + custom CSS files per page
- TypeScript path alias: `@/*` → project root
- Custom types: `CompanySize`, `VCSProvider`, `ApiResponse`
