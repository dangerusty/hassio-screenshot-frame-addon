# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM ${BUILD_FROM}

# Set environment
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

# Install system dependencies for websockets, aiohttp, and Playwright rendering
# Using apk for Alpine Linux compatibility
RUN apk add --no-cache \
    python3 \
    python3-dev \
    py3-pip \
    py3-aiohttp \
    py3-requests \
    py3-pillow \
    build-base \
    openssl-dev \
    libffi-dev \
    jpeg-dev \
    zlib-dev \
    curl \
    git \
    chromium \
    chromium-chromedriver \
    libx11-dev \
    libxcb-dev \
    libxkbcommon-dev \
    freetype-dev \
    mesa-dev \
    ca-certificates

# Ensure python and pip are available
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Install websockets via pip with break-system-packages
RUN python -m pip install --no-cache-dir --break-system-packages \
    'websockets==10.4'

# Install Playwright from PyPI with visible output for debugging
RUN python -m pip install --no-cache-dir --break-system-packages \
    --index-url https://pypi.org/simple/ playwright==1.40.0 || \
    python -m pip install --no-cache-dir --break-system-packages \
    --index-url https://pypi.org/simple/ 'playwright>=1.0' || \
    echo "WARNING: Playwright installation failed, will use system Chromium directly"

# Install samsung-tv-ws-api from xchwarze fork (compatible with websockets==10.4)
RUN python -m pip install --no-cache-dir --break-system-packages \
    git+https://github.com/xchwarze/samsung-tv-ws-api.git

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
