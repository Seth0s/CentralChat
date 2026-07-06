FROM python:3.12-slim

WORKDIR /app

# ADR-016 §13 — video frame sampling (no full clip sent to LLM)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations

RUN chmod +x /app/scripts/compose-entrypoint.sh

EXPOSE 8004

ENTRYPOINT ["/app/scripts/compose-entrypoint.sh"]
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8004"]
