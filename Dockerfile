FROM python:3.13-slim

# System packages needed by Playwright's Chromium installer
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps before copying all code (better layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Install Playwright Chromium + all required system libraries in one step
RUN playwright install chromium --with-deps

# Copy the rest of the application
COPY . .

# Headless mode — no display available in the container
ENV HEADLESS=true

EXPOSE 8080

# --workers 1 is critical: multiple workers = multiple asyncio queues fighting
# over one LinkedIn session. Always keep this at 1.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
