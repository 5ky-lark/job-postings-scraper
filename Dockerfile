# Use python 3.11-slim as base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system dependencies needed for Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and Patchright system dependencies and Chromium browser
RUN python -m playwright install chromium && \
    python -m playwright install-deps chromium && \
    python -m patchright install chromium

# Copy the rest of the application code
COPY . .

# Run the Discord bot by default
CMD ["python", "bot.py"]
