FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    anthropic \
    fastapi \
    uvicorn \
    psycopg2-binary \
    python-dotenv \
    aiohttp \
    pdfplumber

COPY kintsugi/ /app/kintsugi/
COPY deployments/multiverse-school/VALUES.json /app/config/VALUES.json
COPY deployments/multiverse-school/bdi_starter.json /app/config/bdi_starter.json

ENV PYTHONUNBUFFERED=1
ENV KINTSUGI_VALUES_PATH=/app/config/VALUES.json
ENV KINTSUGI_BDI_STARTER=/app/config/bdi_starter.json

EXPOSE 8000

CMD ["uvicorn", "kintsugi.main:app", "--host", "0.0.0.0", "--port", "8000"]
