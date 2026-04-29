# JobPilot Dockerfile — supports linux/amd64 AND linux/arm64 (Raspberry Pi 4/5)
#
# Copilot's original was missing C build deps, so lxml + pdfplumber failed
# to compile their native extensions on ARM64.
#
# Build for Pi:  docker buildx build --platform linux/arm64 -t jobpilot .
FROM python:3.11-slim

# ARM64 build dependencies for lxml, pdfplumber, Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ \
        libxml2-dev libxslt-dev \
        libpoppler-cpp-dev poppler-utils \
        libjpeg-dev zlib1g-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY app.py bot.py scraper.py ./

RUN mkdir -p data logs

EXPOSE 5000

# Uses /health endpoint added to app.py
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

CMD ["python", "app.py"]
