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
    glib \
    nss \
    nspr \
    dbus \
    atk \
    at-spi2-core \
    libxcomposite \
    libxrandr \
    libxinerama \
    libxtst \
    libxss \
    libxdamage \
    pango \
    gtk+3.0 \
    libx11 \
    libxcb \
    libxkbcommon \
    freetype \
    chromium \
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

# Create websockets asyncio.client compatibility shim BEFORE importing samsung-tv-ws-api
# This prevents import errors from the Samsung library
RUN python << 'EOF'
import site
import os

# Get site-packages
site_packages = site.getsitepackages()[0]
ws_path = os.path.join(site_packages, 'websockets')

# Create asyncio submodule with client shim
asyncio_path = os.path.join(ws_path, 'asyncio')
os.makedirs(asyncio_path, exist_ok=True)

# Create __init__.py that re-exports from websockets.client
with open(os.path.join(asyncio_path, '__init__.py'), 'w') as f:
    f.write('''try:
    from websockets.client import *
except Exception:
    pass
try:
    from websockets import client
except Exception:
    pass
''')

# Create client.py that FULLY re-exports from websockets.client with __all__
with open(os.path.join(asyncio_path, 'client.py'), 'w') as f:
    f.write('''from websockets import client

# Re-export all symbols from websockets.client module
connect = client.connect
ClientConnection = client.ClientConnection
__all__ = [attr for attr in dir(client) if not attr.startswith('_')]
''')

# Create websockets/protocol.py shim for libraries that expect old API
protocol_py = os.path.join(ws_path, 'protocol.py')
if not os.path.exists(protocol_py):
    with open(protocol_py, 'w') as f:
        f.write('''# Compatibility shim for websockets.protocol (old API)
import enum

class State(enum.IntEnum):
    CONNECTING = 0
    OPEN = 1
    CLOSING = 2
    CLOSED = 3

CLIENT = 1
SERVER = 2
CONNECTING = State.CONNECTING
OPEN = State.OPEN
CLOSING = State.CLOSING
CLOSED = State.CLOSED

# Re-export from actual websockets.protocol if it exists
try:
    from websockets.protocol import *
except ImportError:
    pass
''')

print('Created websockets compatibility shims')
EOF

# NOW install samsung-tv-ws-api which depends on the above shim
RUN python -m pip install --no-cache-dir \
    git+https://github.com/NickWaterton/samsung-tv-ws-api.git

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
