FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini MANIFEST.in ./
COPY alembic ./alembic
COPY src ./src
COPY samples ./samples

RUN pip install --upgrade pip && pip install ".[browser]" \
    && playwright install --with-deps chromium

ENV HEALSCRAPE_DATA_DIR=/data
RUN mkdir -p /data

ENTRYPOINT ["scrape"]
CMD ["--help"]
