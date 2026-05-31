# LSP Website

The Lacanian School of Psychoanalysis registration and payment website — a Django application.

This repository began as **Phase 1** of the LSP website (user accounts and roles, event registration, payments) and now also carries a number of Phase 2 features that were pulled forward and deployed: a public member directory, a member profile editor, a publications "works" showcase, shared documents, cartels/working-groups, and **Parlêtre** — a members-only discussion board (multi-channel forum + realtime chat). The site is live at `app.lacanschool.org`. See the planning documents in the parent `LSP-Web-Coordinator` folder — the Requirements Specification, the Phase 1 Architecture & Data Model design, and the Phase 2 plan — for scope and rationale.

## Tech stack

- Django 5.2 LTS on Python 3.10+
- PostgreSQL in production; SQLite for local development
- Stripe for payments; Amazon SES for email (incl. inbound reply-by-email)
- Django Channels + daphne (ASGI) for Parlêtre's realtime chat
- Tailwind v4 + DaisyUI v5 for styling (`npm run build:css`)
- Dependency and environment management with [uv](https://docs.astral.sh/uv/)

## Getting started

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/).

```
# Install dependencies (uv creates the virtual environment automatically)
uv sync

# Apply database migrations (creates db.sqlite3 for local development)
uv run python manage.py migrate

# Create an administrator account
uv run python manage.py createsuperuser

# Run the development server
uv run python manage.py runserver
```

The site is then at http://localhost:8000/ and the admin at http://localhost:8000/admin/.

## Project layout

```
config/         Django project — settings, URLs, WSGI/ASGI entry points
  settings/     base.py, development.py, production.py
accounts/       User accounts, roles, profiles, directory
committees/     Committees and memberships
events/         Events, seminars, and pricing
registrations/  Event registrations
payments/       Payments, receipts, Stripe, dues + tuition lifecycle
core/           Shared utilities, calendar, rendered docs
content/        Editable site pages
works/          Member/faculty publications showcase
documents/      Newsletters and shared documents
parletre/       Parlêtre members-only discussion board (forum + chat)
workgroups/     Shared collaborative layer (cartels/working-groups/seminars)
cartels/        Cartels, built on the workgroup layer
```

## Settings

Settings are split by environment. Development is the default; production is selected with an environment variable:

```
DJANGO_SETTINGS_MODULE=config.settings.production
```

Configuration is read from environment variables, and from an optional `.env` file during local development. See `.env.example` for the available variables.

## Tests and linting

```
uv run pytest
uv run ruff check .
```

## Deployment

The site is hosted on AWS and runs on PostgreSQL in production. Production requires `DJANGO_SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, and the email variables to be set in the environment. See the Phase 1 Architecture document for the full deployment design.
