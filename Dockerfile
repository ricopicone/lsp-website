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
# Tailwind v4 scans templates at build time for class names; any class only
# referenced in templates that aren't COPYed here is silently dropped from
# the output bundle. Glob every <app>/templates dir so adding a new app
# doesn't require editing this Dockerfile. (Missed works/ + documents/
# previously, which broke vibe-card avatars in prod.)
COPY --parents */templates ./
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
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile - --error-logfile -"]
