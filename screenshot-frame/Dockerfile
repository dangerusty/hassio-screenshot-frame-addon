# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
# Use HA's Python base image (Alpine-based) optimized for add-ons
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.14-alpine3.23
FROM ${BUILD_FROM}

# Set environment
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1


# Install system dependencies
# Ensure Python and pip present even if base image is non-python
RUN apk add --no-cache \
    python3 \
    python3-dev \
    py3-pip \
    chromium \
    build-base \
    openssl-dev \
    libffi-dev \
    jpeg-dev \
    zlib-dev \
    curl \
    git \
    libx11-dev \
    libxcb-dev \
    libxkbcommon-dev \
    freetype-dev \
    mesa-dev \
    ca-certificates

# Ensure python and pip is up to date
RUN python3 -m pip install --break-system-packages --upgrade pip setuptools wheel

# Configure pip to use PyPI (and HA wheels for musllinux where available)
RUN mkdir -p ~/.pip && echo '[global]\nindex-url = https://pypi.org/simple/\nextra-index-url = https://wheels.home-assistant.io/musllinux-index/' > ~/.pip/pip.conf

# Copy requirements.txt and install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir -r /tmp/requirements.txt

# Create app and data directories
RUN mkdir -p /app /data

# Copy addon files
COPY main.py /app/main.py
COPY run.sh /app/run.sh

# Set working directory
WORKDIR /app

# Make run script executable
RUN chmod +x /app/run.sh

# Expose HTTP port for the addon server
EXPOSE 8200

# Run the addon
CMD ["/app/run.sh"]
