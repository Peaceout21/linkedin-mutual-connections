FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install only what the thin API needs — no browser, no playwright, no Gemini
# Scraping runs on the local worker machine, not here
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    google-cloud-firestore \
    google-cloud-pubsub \
    google-cloud-secret-manager \
    pydantic-settings \
    python-dotenv

# Copy only the API package
COPY api/ api/

EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
