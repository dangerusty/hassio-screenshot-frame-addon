# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM ${BUILD_FROM}

# Set environment
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

# Install system dependencies for websockets, aiohttp, and Playwright rendering
# Using apk for Alpine Linux compatibility
RUN apk add --no-cache \
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

# Install dependencies using pip
RUN python -m pip install --no-cache-dir \
    aiohttp==3.8.4 \
    requests==2.31.0 \
    Pillow==10.0.0 \
    websockets==10.4 \
    playwright==1.40.0

# Install Playwright browsers
RUN python -m playwright install chromium

# Install samsung-tv-ws-api from xchwarze fork (compatible with websockets==10.4)
RUN python -m pip install --no-cache-dir \
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
