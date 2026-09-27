FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8501 \
    CRAWL_DB_PATH=/data/crawl.sqlite3

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY streamlit_app.py ./
COPY components ./components

RUN pip install --upgrade pip && pip install uv && uv pip install --system .

RUN mkdir -p /data

EXPOSE 8501

CMD ["sh", "-c", "streamlit run streamlit_app.py --server.headless true --server.address 0.0.0.0 --server.port ${PORT:-8501}"]
