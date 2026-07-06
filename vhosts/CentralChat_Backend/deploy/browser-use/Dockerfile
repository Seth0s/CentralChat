# Browser-Use Sidecar for CentralChat
# Provides web_search tool via HTTP API — no API keys in this container.
#
# Usage:
#   docker compose up -d
#   curl -X POST http://localhost:8081/search -H 'Content-Type: application/json' -d '{"query":"golang release notes","limit":3}'

FROM python:3.12-slim

RUN pip install --no-cache-dir \
    browser-use \
    langchain-openai \
    playwright

RUN playwright install --with-deps chromium
RUN playwright install-deps

WORKDIR /app
COPY server.py .

EXPOSE 8081
CMD ["python3", "server.py"]
