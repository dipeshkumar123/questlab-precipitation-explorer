FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

COPY frontend ./frontend
COPY scripts/build_frontend.py ./scripts/build_frontend.py
ENV QUEST_API_BASE_URL=
RUN python scripts/build_frontend.py

COPY data/processed ./data/processed
ENV QUEST_DATA_DIR=/app/data
ENV QUEST_STATIC_DIR=/app/dist
ENV QUEST_FRESHNESS_HOURS=12
ENV QUEST_API_HOST=0.0.0.0
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn questlab.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
