# syntax=docker/dockerfile:1.7

# --- Stage 1: install Python deps with uv -----------------------------------
FROM python:3.10-slim AS python-build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Stage 2: build Tailwind + DaisyUI CSS ----------------------------------
FROM node:20-slim AS css-build
WORKDIR /css
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY assets/css ./assets/css
# Tailwind v4 scans these templates at build time for class names. Any
# class only referenced in a templates dir that isn't COPYed here is
# silently dropped from the output bundle — keep this list in sync with
# every app that has a templates/ dir, or Tailwind will quietly stop
# emitting classes that page templates rely on. (Forgetting works/ +
# documents/ here broke vibe-card avatars on prod.)
COPY accounts/templates ./accounts/templates
COPY admissions/templates ./admissions/templates
COPY content/templates ./content/templates
COPY core/templates ./core/templates
COPY documents/templates ./documents/templates
COPY events/templates ./events/templates
COPY parletre/templates ./parletre/templates
COPY payments/templates ./payments/templates
COPY registrations/templates ./registrations/templates
COPY works/templates ./works/templates
COPY workgroups/templates ./workgroups/templates
COPY cartels/templates ./cartels/templates
COPY workinggroups/templates ./workinggroups/templates
COPY video/templates ./video/templates
RUN npx tailwindcss -i ./assets/css/input.css -o ./static/css/site.css --minify

# --- Stage 3: runtime --------------------------------------------------------
FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.production
RUN useradd --create-home --uid 1000 app && mkdir -p /app/staticfiles && chown -R app:app /app
WORKDIR /app
COPY --from=python-build --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app . /app
# Drop in the freshly-built CSS from the css-build stage (overwriting any
# stale local copy that might have been COPYed in by the previous step).
COPY --from=css-build --chown=app:app /css/static/css/site.css /app/static/css/site.css
USER app
EXPOSE 8000
# Served under ASGI (daphne) so Parlêtre's WebSocket chat works alongside
# HTTP. Channels' WebSocket layer is shared across processes via Redis
# (REDIS_URL) — see compose.yml and config/settings/production.py.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && exec daphne -b 0.0.0.0 -p 8000 config.asgi:application"]
