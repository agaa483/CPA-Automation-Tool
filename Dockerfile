# Backend container for Fly.io.
# Runs FastAPI + a persistent-volume SQLite database + litestream backups to S3.

FROM python:3.11-slim

# System deps + litestream binary. build-essential/libffi/libssl needed for
# native Python wheels (cryptography, pydantic-core, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    build-essential \
    libffi-dev \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.deb \
    -o /tmp/litestream.deb \
    && dpkg -i /tmp/litestream.deb \
    && rm /tmp/litestream.deb

WORKDIR /app

# Install Python deps
COPY requirements.txt .
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r backend/requirements.txt

# Copy source
COPY src/ src/
COPY backend/ backend/
COPY litestream.yml /etc/litestream.yml
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Data directory lives on the mounted volume
ENV DB_PATH=/data/app.db

EXPOSE 8001

CMD ["/entrypoint.sh"]
