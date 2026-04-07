FROM python:3.12-slim

# ── System dependencies for Selenium + Firefox ──────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        firefox-esr \
        wget \
        curl \
        unzip \
        zip \
        libgtk-3-0 \
        libdbus-glib-1-2 \
        libx11-xcb1 \
        libxt6 \
    && rm -rf /var/lib/apt/lists/*

# ── Geckodriver ─────────────────────────────────────────────────────────
ARG GECKODRIVER_VERSION=0.35.0
RUN wget -q "https://github.com/mozilla/geckodriver/releases/download/v${GECKODRIVER_VERSION}/geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz" \
    && tar -xzf geckodriver-*.tar.gz -C /usr/local/bin/ \
    && rm geckodriver-*.tar.gz \
    && chmod +x /usr/local/bin/geckodriver

WORKDIR /app

# ── Python dependencies ─────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ────────────────────────────────────────────────────
COPY pipeline/ pipeline/
COPY plugins/ plugins/
COPY run.py .
COPY config.yaml .
COPY cluster.yaml.example .

# Data directories (mounted as volumes in production)
RUN mkdir -p /app/data/input /app/data/output/xyz /app/data/output/figures /app/data/output/packages /app/data/output/pilots /app/data/downloads /app/data/db

CMD ["python", "run.py"]
