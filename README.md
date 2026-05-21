# LSP Website

The Lacanian School of Psychoanalysis registration and payment website — a Django application.

This repository implements **Phase 1** of the LSP website: user accounts and roles, event registration, and payments. See the planning documents in the parent `LSP-Web-Coordinator` folder — the Requirements Specification and the Phase 1 Architecture & Data Model design — for scope and rationale.

## Tech stack

- Django 5.2 LTS on Python 3.10+
- PostgreSQL in production; SQLite for local development
- Stripe for payments; Amazon SES for email
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
accounts/       User accounts and roles
events/         Events, seminars, and pricing
registrations/  Event registrations
payments/       Payments, receipts, and the Stripe integration
core/           Shared utilities
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
