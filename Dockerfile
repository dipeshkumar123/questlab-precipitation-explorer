FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nginx supervisor gettext-base \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

COPY frontend ./frontend
COPY scripts/build_frontend.py ./scripts/build_frontend.py
COPY deploy/nginx.conf.template ./deploy/nginx.conf.template
COPY deploy/supervisord.conf ./deploy/supervisord.conf
COPY scripts/container_entrypoint.sh ./scripts/container_entrypoint.sh
ENV QUEST_API_BASE_URL=
RUN python scripts/build_frontend.py

COPY data/processed ./data/processed
ENV QUEST_DATA_DIR=/app/data
ENV QUEST_FRESHNESS_HOURS=12
ENV QUEST_API_HOST=127.0.0.1
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "scripts/container_entrypoint.sh"]
