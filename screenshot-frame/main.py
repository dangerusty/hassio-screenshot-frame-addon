import os
import asyncio
import json
import logging
import warnings
from datetime import datetime
from aiohttp import web, ClientSession, BasicAuth
from pathlib import Path

# Suppress SSL warnings for local network devices
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# pyppeteer for browser automation (Python port of Puppeteer)
import pyppeteer

# MQTT for Home Assistant integration
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# Configure logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

_preferred_path = Path('/data/art.jpg')
# If /data is writable (typical add-on runtime), use it; otherwise fall back to
# the workspace-local `./data/art.jpg` so local testing doesn't require root.
if _preferred_path.parent.exists() or os.access(str(_preferred_path.parent), os.W_OK):
    ART_PATH = _preferred_path
else:
    ART_PATH = Path('./data/art.jpg')
    

# Ensure the chosen data directory exists
try:
    ART_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

INTERVAL = int(os.environ.get('INTERVAL_SECONDS', os.environ.get('INTERVAL', 300)))
SCREENSHOT_WIDTH = int(os.environ.get('SCREENSHOT_WIDTH', '1920'))
SCREENSHOT_HEIGHT = int(os.environ.get('SCREENSHOT_HEIGHT', '1080'))
SCREENSHOT_ZOOM = int(os.environ.get('SCREENSHOT_ZOOM', '100'))  # percentage: 100 = 100%, 150 = 150%, etc.
SCREENSHOT_WAIT = float(os.environ.get('SCREENSHOT_WAIT', '0.0'))  # seconds to wait after network idle (0 = no additional wait)
SCREENSHOT_SKIP_NAVIGATION = os.environ.get('SCREENSHOT_SKIP_NAVIGATION', 'false').lower() in ('1','true','yes')  # Skip page reload, just take new screenshot

# Logging
DEBUG_LOGGING = os.environ.get('DEBUG_LOGGING', 'false').lower() in ('1','true','yes')
if not DEBUG_LOGGING:
    logging.getLogger().setLevel(logging.WARNING)

# Local TV options (from add-on options.json exported by run.sh)
TV_IP = os.environ.get('TV_IP') or ''
TV_PORT = int(os.environ.get('TV_PORT', '8001'))
TV_MATTE = os.environ.get('TV_MATTE') or None
TV_SHOW_AFTER_UPLOAD = os.environ.get('TV_SHOW_AFTER_UPLOAD', 'true').lower() in ('1','true','yes')
TV_UPLOAD_TIMEOUT = int(os.environ.get('TV_UPLOAD_TIMEOUT', '60'))  # seconds (default: 60s)
TARGET_URL = os.environ.get('TARGET_URL') or ''
# Target URL auth settings (supports multiple auth types)
# TARGET_AUTH_TYPE: none|bearer|basic|headers
TARGET_AUTH_TYPE = os.environ.get('TARGET_AUTH_TYPE', 'none').lower()
TARGET_TOKEN = os.environ.get('TARGET_TOKEN')
TARGET_TOKEN_HEADER = os.environ.get('TARGET_TOKEN_HEADER', 'Authorization')
TARGET_TOKEN_PREFIX = os.environ.get('TARGET_TOKEN_PREFIX', 'Bearer')
TARGET_USERNAME = os.environ.get('TARGET_USERNAME')
TARGET_PASSWORD = os.environ.get('TARGET_PASSWORD')
TARGET_HEADERS = os.environ.get('TARGET_HEADERS')  # optional JSON map of headers

# Always replace last art file (hard-coded path for persistence)
TV_LAST_ART_FILE = '/data/last-art-id.txt'

# MQTT configuration (optional Home Assistant integration)
MQTT_ENABLED = os.environ.get('MQTT_ENABLED', 'false').lower() in ('1','true','yes')
MQTT_BROKER = os.environ.get('MQTT_BROKER', 'localhost')
MQTT_PORT = int(os.environ.get('MQTT_PORT', '1883'))
MQTT_USERNAME = os.environ.get('MQTT_USERNAME')
MQTT_PASSWORD = os.environ.get('MQTT_PASSWORD')
MQTT_TOPIC_BASE = os.environ.get('MQTT_TOPIC_BASE', 'homeassistant')  # Discovery uses homeassistant/ prefix

logger.info('Screenshot to Samsung Frame Addon - Starting')
if DEBUG_LOGGING:
    logger.info('='*60)
    logger.info(f'Configuration:')
    logger.info(f'  Target URL: {TARGET_URL if TARGET_URL else "NOT SET"}')
    logger.info(f'  Auth Type: {TARGET_AUTH_TYPE}')
    logger.info(f'  Interval: {INTERVAL}s')
    logger.info(f'  Screenshot: {SCREENSHOT_WIDTH}x{SCREENSHOT_HEIGHT} @ {SCREENSHOT_ZOOM}% zoom')
    logger.info(f'  Screenshot Wait: {SCREENSHOT_WAIT}s (after network idle)')
    logger.info(f'  Screenshot Skip Navigation: {SCREENSHOT_SKIP_NAVIGATION}')
    logger.info(f'  Art Path: {ART_PATH}')
    logger.info(f'  TV Upload: {"ENABLED" if TV_IP else "DISABLED"}')
    if TV_IP:
        logger.info(f'  TV IP: {TV_IP}:{TV_PORT}')
        logger.info(f'  TV Matte: {TV_MATTE if TV_MATTE else "none"}')
        logger.info(f'  TV Show After Upload: {TV_SHOW_AFTER_UPLOAD}')
        logger.info(f'  TV Upload Timeout: {TV_UPLOAD_TIMEOUT}s')
    logger.info(f'  Debug Logging: {DEBUG_LOGGING}')
    logger.info(f'  MQTT: {"ENABLED" if MQTT_ENABLED else "DISABLED"}')
    if MQTT_ENABLED:
        logger.info(f'  MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}')
        logger.info(f'  MQTT Topic Base: {MQTT_TOPIC_BASE}')
        from samsungtvws import SamsungTVArt
    except Exception as e:
        logger.error(f'[TV UPLOAD] ERROR: samsungtvws library not available: {e}')
        return None

    def _sync_upload():
        """Synchronous upload function to run in executor."""
        token_file = '/data/tv-token.txt'
        tv = None
        # Create local copy of show parameter so we can modify it
        local_show = show
        try:
            logger.debug(f'[TV UPLOAD] Connecting to TV (token file: {token_file})')
            tv = SamsungTVArt(host=host, port=port, token_file=token_file)
            tv.open()

            supported = tv.supported()
            if not supported:
                logger.error('[TV UPLOAD] ERROR: TV does not support art mode via this API')
                tv.close()
                return None

            # read image bytes
            logger.debug(f'[TV UPLOAD] Reading image from {image_path}')
            with open(image_path, 'rb') as f:
                data = f.read()
            logger.debug(f'[TV UPLOAD] Image size: {len(data)} bytes')

            file_type = os.path.splitext(image_path)[1][1:].upper() or 'JPEG'
            logger.debug(f'[TV UPLOAD] Uploading image (type={file_type}, matte={matte}, show={local_show})')
            
            # Get cached ID for cleanup after upload
            last_id = None
            if os.path.exists(TV_LAST_ART_FILE):
                try:
                    with open(TV_LAST_ART_FILE, 'r') as lf:
                        last_id = lf.read().strip() or None
                    if last_id:
                        logger.debug(f'[TV UPLOAD] Found cached art ID: {last_id}')
                except Exception:
                    pass

            # Upload new art
            logger.debug('[TV UPLOAD] Uploading new art entry')
            content_id = None
            try:
                if matte:
                    content_id = tv.upload(data, file_type=file_type.lower(), matte=matte)
                else:
                    content_id = tv.upload(data, file_type=file_type.lower())
            except TypeError:
                content_id = tv.upload(data, file_type=file_type.lower())

            logger.debug(f'[TV UPLOAD] Upload returned id: {content_id}')
            if content_id is not None:
                # Check if TV is in art mode - if so, force show=True so image actually displays
                try:
                    art_mode_status = tv.get_artmode()
                    logger.debug(f'[TV UPLOAD] TV art mode status: {art_mode_status} (type: {type(art_mode_status).__name__})')
                    # If TV is in art mode, force show=True to make the image display
                    # Check various possible return values: 'on', 'On', True, etc.
                    if art_mode_status and str(art_mode_status).lower() in ('on', 'true', '1'):
                        local_show = True
                        logger.debug('[TV UPLOAD] TV is in art mode, forcing show=True')
                except Exception as e:
                    logger.debug(f'[TV UPLOAD] Could not check art mode status: {e}')
                
                logger.debug(f'[TV UPLOAD] Attempting to select image on TV (show={local_show})')
                selection_successful = False
                try:
                    # Try to select with show parameter (controls whether image is displayed)
                    tv.select_image(content_id, show=local_show)
                    logger.debug(f'[TV UPLOAD] ✓ Selected uploaded image on TV (show={local_show})')
                    selection_successful = True
                except TypeError:
                    # If show parameter not supported, try without it
                    try:
                        tv.select_image(content_id)
                        logger.debug('[TV UPLOAD] ✓ Selected uploaded image on TV (without show parameter)')
                        selection_successful = True
                    except Exception as e:
                        logger.error(f'[TV UPLOAD] ERROR: Failed to select uploaded image: {e}')
                except Exception as e:
                    logger.error(f'[TV UPLOAD] ERROR: Failed to select uploaded image: {e}')

                # Delete old art only after new art is successfully selected
                if selection_successful and last_id and last_id != content_id:
                    try:
                        logger.debug(f'[TV UPLOAD] Deleting previous art entry: {last_id}')
                        tv.delete(last_id)
                        logger.debug('[TV UPLOAD] ✓ Previous art deleted')
                    except Exception as e:
                        logger.warning(f'[TV UPLOAD] Warning: Failed to delete previous art: {e}')

            tv.close()
            logger.debug('[TV UPLOAD] TV connection closed')

            # Persist last art id for future replace attempts (only if selection was successful)
            try:
                if content_id and selection_successful:
                    with open(TV_LAST_ART_FILE, 'w') as lf:
                        lf.write(str(content_id))
                    logger.debug(f'[TV UPLOAD] ✓ Cached art ID {content_id} to {TV_LAST_ART_FILE}')
            except Exception as e:
                logger.warning(f'[TV UPLOAD] Warning: Failed to cache art ID: {e}')

            return content_id
            
        except Exception as e:
            logger.error(f'[TV UPLOAD] ERROR: Exception during TV interaction: {e}')
            try:
                if tv:
                    tv.close()
            except Exception:
                pass
            return None

    # Run sync function in thread executor with timeout
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _sync_upload),
            timeout=TV_UPLOAD_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.info(f'[TV UPLOAD] ERROR: Upload timed out after {TV_UPLOAD_TIMEOUT}s')
        return None


# Global browser and page instances for persistent rendering
_browser = None
_page = None
_page_lock = asyncio.Lock()

# Status tracking for API
_status_lock = asyncio.Lock()
_last_sync_time = None
_last_sync_success = False
_last_error = None

# MQTT client and state
_mqtt_client = None
_mqtt_connected = False
_mqtt_lock = asyncio.Lock()

async def _ensure_browser(width: int, height: int):
    """Ensure browser instance is running. Returns (browser, page)."""
    global _browser, _page
    
    # Check if browser is still connected
    if _browser is not None:
        try:
            # Test if browser is still alive
            await _browser.version()
        except Exception:
            logger.debug('[BROWSER] Browser connection lost, relaunching...')
            _browser = None
            _page = None
    
    if _browser is None:
        logger.debug('[BROWSER] Launching persistent browser instance...')
        executable_candidates = ['/usr/bin/chromium-browser', '/usr/bin/chromium']
        executable_path = None
        for cand in executable_candidates:
            if os.path.exists(cand):
                executable_path = cand
                break
        
        try:
            if executable_path:
                _browser = await pyppeteer.launch(headless=True, executablePath=executable_path)
            else:
                _browser = await pyppeteer.launch(headless=True)
        except Exception:
            args = ['--no-sandbox']
            if executable_path:
                _browser = await pyppeteer.launch(headless=True, executablePath=executable_path, args=args)
            else:
                _browser = await pyppeteer.launch(headless=True, args=args)
        
        logger.debug('[BROWSER] ✓ Browser launched successfully')
        _page = None  # Force new page creation
    
    if _page is None:
        logger.debug('[BROWSER] Creating new page...')
        _page = await _browser.newPage()
        await _page.setViewport({'width': width, 'height': height})
        logger.debug('[BROWSER] ✓ Page created')
    
    return _browser, _page


async def render_url_with_pyppeteer(url: str, headers: dict | None = None, timeout: int = 30000, width: int = 1920, height: int = 1080, zoom: int = 100, skip_navigation: bool = False):
    """Render the given URL to a PNG using pyppeteer and return bytes.

    Args:
        zoom: Zoom percentage (100 = 100%, 150 = 150%, 50 = 50%)
        skip_navigation: If True, skip page reload and just take a new screenshot (for auto-refreshing pages like DakBoard)

    Uses persistent browser instance for faster subsequent renders.
    """
    async with _page_lock:
        browser, page = await _ensure_browser(width, height)
        
        # Set extra headers if provided (only on first load or when navigation isn't skipped)
        if headers and not skip_navigation:
            await page.setExtraHTTPHeaders(headers)
        
        # Navigate to URL - use 'networkidle2' to wait for most network activity to complete
        # This waits until there are ≤2 network connections for 500ms (ideal for dynamic content)
        if not skip_navigation:
            logger.debug('[BROWSER] Navigating to URL...')
            await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': timeout})
            
            # Optional additional wait after network idle (configurable via SCREENSHOT_WAIT)
            if SCREENSHOT_WAIT > 0:
                await asyncio.sleep(SCREENSHOT_WAIT)
        else:
            logger.debug('[BROWSER] Skipping navigation (page auto-refreshes), taking new screenshot...')
            # Still wait a moment for any auto-refresh content to settle
            if SCREENSHOT_WAIT > 0:
                await asyncio.sleep(SCREENSHOT_WAIT)
        
        # Apply zoom by scaling the page
        if zoom != 100:
            await page.evaluate(f'() => {{ document.body.style.zoom = "{zoom}%" }}')
        
        # Take screenshot
        logger.debug('[BROWSER] Taking screenshot...')
        screenshot = await page.screenshot({'fullPage': False})
        logger.debug('[BROWSER] ✓ Screenshot captured')
        
        return screenshot


def _on_mqtt_connect(client, userdata, flags, rc):
    """MQTT connect callback."""
    global _mqtt_connected
    if rc == 0:
        logger.info('[MQTT] ✓ Connected to MQTT broker')
        _mqtt_connected = True
        # Publish discovery messages for sensors
        try:
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(_mqtt_publish_discovery(), loop)
        except Exception:
            pass
    else:
        logger.error(f'[MQTT] Connection failed with code {rc}')
        _mqtt_connected = False


def _on_mqtt_disconnect(client, userdata, rc):
    """MQTT disconnect callback."""
    global _mqtt_connected
    _mqtt_connected = False
    if rc != 0:
        logger.warning(f'[MQTT] Unexpected disconnection with code {rc}')


async def _mqtt_publish_discovery():
    """Publish Home Assistant MQTT Discovery messages for sensors."""
    global _mqtt_client
    if not _mqtt_client or not _mqtt_connected:
        return
    
    device_id = 'screenshot_frame'
    device_info = {
        'identifiers': ['screenshot_to_samsung_frame_addon'],
        'name': 'Screenshot to Samsung Frame',
        'manufacturer': 'Home Assistant Community',
        'model': 'Screenshot Frame Add-on',
    }
    
    # Discovery message for last_sync sensor
    discovery_topic = f'{MQTT_TOPIC_BASE}/sensor/{device_id}/last_sync/config'
    discovery_payload = {
        'name': 'Screenshot Frame Last Sync',
        'unique_id': f'{device_id}_last_sync',
        'state_topic': f'screenshot_frame/last_sync',
        'device_class': 'timestamp',
        'device': device_info,
    }
    _mqtt_client.publish(discovery_topic, json.dumps(discovery_payload), retain=True)
    logger.debug(f'[MQTT] Published discovery for last_sync')
    
    # Discovery message for success sensor
    discovery_topic = f'{MQTT_TOPIC_BASE}/binary_sensor/{device_id}/success/config'
    discovery_payload = {
        'name': 'Screenshot Frame Sync Success',
        'unique_id': f'{device_id}_success',
        'state_topic': f'screenshot_frame/success',
        'device_class': 'connectivity',
        'device': device_info,
    }
    _mqtt_client.publish(discovery_topic, json.dumps(discovery_payload), retain=True)
    logger.debug(f'[MQTT] Published discovery for success')
    
    # Discovery message for error sensor
    discovery_topic = f'{MQTT_TOPIC_BASE}/sensor/{device_id}/error/config'
    discovery_payload = {
        'name': 'Screenshot Frame Last Error',
        'unique_id': f'{device_id}_error',
        'state_topic': f'screenshot_frame/error',
        'device': device_info,
    }
    _mqtt_client.publish(discovery_topic, json.dumps(discovery_payload), retain=True)
    logger.debug(f'[MQTT] Published discovery for error')


async def _mqtt_update_status():
    """Publish current status to MQTT."""
    global _mqtt_client, _mqtt_connected, _last_sync_time, _last_sync_success, _last_error
    
    if not MQTT_ENABLED or not _mqtt_client or not _mqtt_connected:
        return
    
    async with _status_lock:
        try:
            # Publish last_sync timestamp
            if _last_sync_time:
                _mqtt_client.publish('screenshot_frame/last_sync', _last_sync_time.isoformat(), retain=True)
            
            # Publish success status as ON/OFF
            state = 'ON' if _last_sync_success else 'OFF'
            _mqtt_client.publish('screenshot_frame/success', state, retain=True)
            
            # Publish error message (empty if no error)
            error_msg = _last_error if _last_error else 'None'
            _mqtt_client.publish('screenshot_frame/error', error_msg, retain=True)
            
            logger.debug(f'[MQTT] Published status update (success={_last_sync_success})')
        except Exception as e:
            logger.error(f'[MQTT] Error publishing status: {e}')


async def _mqtt_connect():
    """Initialize and connect MQTT client."""
    global _mqtt_client, _mqtt_connected
    
    if not MQTT_ENABLED or not MQTT_AVAILABLE:
        logger.debug('[MQTT] MQTT disabled or paho-mqtt not available')
        return
    
    try:
        _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id='screenshot_frame_addon')
        _mqtt_client.on_connect = _on_mqtt_connect
        _mqtt_client.on_disconnect = _on_mqtt_disconnect
        
        if MQTT_USERNAME and MQTT_PASSWORD:
            _mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            logger.debug(f'[MQTT] Using authentication')
        
        logger.debug(f'[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT}...')
        _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        _mqtt_client.loop_start()
        
        # Give it a moment to connect
        await asyncio.sleep(2)
        
    except Exception as e:
        logger.error(f'[MQTT] Failed to initialize MQTT: {e}')
        _mqtt_client = None


async def _mqtt_disconnect():
    """Disconnect MQTT client."""
    global _mqtt_client, _mqtt_connected
    
    if _mqtt_client:
        try:
            _mqtt_client.loop_stop()
            _mqtt_client.disconnect()
            logger.debug('[MQTT] Disconnected')
        except Exception:
            pass
        finally:
            _mqtt_client = None
            _mqtt_connected = False


async def screenshot_loop():
    logger.debug('[LOOP] Screenshot loop started')
    if not TARGET_URL:
        logger.warning('[LOOP] WARNING: No TARGET_URL configured; the add-on will not fetch screenshots')

    global _last_sync_time, _last_sync_success, _last_error
    loop_count = 0
    next_cycle_time = None
    
    while True:
        loop_count += 1
        cycle_start = asyncio.get_event_loop().time()
        logger.debug(f'\n[LOOP] ===== Cycle #{loop_count} started =====')
        try:
            if not TARGET_URL:
                logger.debug('[LOOP] Skipping fetch; TARGET_URL not set')
            else:
                try:
                    # Build headers/auth dynamically so the target URL can be
                    # Home Assistant (token header), DakBoard (basic auth), or
                    # any other URL requiring custom headers.
                    headers = {}
                    auth = None
                    if TARGET_HEADERS:
                        try:
                            parsed = json.loads(TARGET_HEADERS)
                            if isinstance(parsed, dict):
                                headers.update(parsed)
                        except Exception:
                            logger.warning('Failed to parse TARGET_HEADERS; expecting JSON map')

                    if TARGET_AUTH_TYPE == 'bearer' and TARGET_TOKEN:
                        headers[TARGET_TOKEN_HEADER] = f"{TARGET_TOKEN_PREFIX} {TARGET_TOKEN}"
                    elif TARGET_AUTH_TYPE == 'basic' and TARGET_USERNAME and TARGET_PASSWORD:
                        auth = BasicAuth(TARGET_USERNAME, TARGET_PASSWORD)

                    async with ClientSession() as session:
                        logger.debug(f'Fetching from target URL: {TARGET_URL} (auth={TARGET_AUTH_TYPE})')
                        async with session.get(TARGET_URL, timeout=30, headers=headers or None, auth=auth) as resp:
                            if resp.status == 200:
                                ctype = (resp.headers.get('content-type') or '').lower()
                                content = await resp.read()
                                # If the target returns HTML, render it with pyppeteer
                                if ctype.startswith('text/html') or (len(content) > 0 and content.lstrip().startswith(b'<')):
                                    logger.debug('Target returned HTML; attempting pyppeteer render')
                                    # Skip navigation after first load if configured (for auto-refreshing pages)
                                    skip_nav = SCREENSHOT_SKIP_NAVIGATION and loop_count > 1
                                    rendered = await render_url_with_pyppeteer(TARGET_URL, headers=headers, width=SCREENSHOT_WIDTH, height=SCREENSHOT_HEIGHT, zoom=SCREENSHOT_ZOOM, skip_navigation=skip_nav)
                                    if rendered:
                                        with open(str(ART_PATH), 'wb') as f:
                                            f.write(rendered)
                                        logger.debug(f'Saved pyppeteer-rendered image to {ART_PATH}')
                                    else:
                                        # Fallback: save the raw response (likely HTML) for debugging
                                        with open(str(ART_PATH), 'wb') as f:
                                            f.write(content)
                                        logger.warning(f'pyppeteer not available or failed; saved raw target response to {ART_PATH}')
                                else:
                                    with open(str(ART_PATH), 'wb') as f:
                                        f.write(content)
                                    logger.debug(f'Saved image from target to {ART_PATH}')
                            else:
                                logger.warning(f'Target URL returned status {resp.status}')
                except Exception as e:
                    logger.error(f'Error fetching from target URL: {e}')
                    async with _status_lock:
                        _last_error = str(e)
        except Exception as e:
            logger.error(f'Fetch loop error: {e}')
            async with _status_lock:
                _last_error = str(e)

        if TV_IP:
            logger.debug(f'[LOOP] TV upload enabled, uploading to {TV_IP}:{TV_PORT}')
            try:
                content_id = await upload_image_to_tv_async(TV_IP, TV_PORT, str(ART_PATH), TV_MATTE, TV_SHOW_AFTER_UPLOAD)
                if not content_id:
                    logger.warning('[LOOP] WARNING: Async upload returned no id; upload may have failed')
                    async with _status_lock:
                        _last_sync_success = False
                        _last_error = 'Upload returned no ID'
                else:
                    logger.debug(f'[LOOP] ✓ Upload complete with id: {content_id}')
                    async with _status_lock:
                        _last_sync_time = datetime.now()
                        _last_sync_success = True
                        _last_error = None
                    await _mqtt_update_status()
            except Exception as e:
                logger.error(f'[LOOP] ERROR: Local TV upload error: {e}')
                import traceback
                traceback.print_exc()
                async with _status_lock:
                    _last_sync_success = False
                    _last_error = str(e)
                await _mqtt_update_status()
        else:
            logger.debug('[LOOP] TV upload disabled (use_local_tv=false or tv_ip not set)')
            # Still mark as success if just fetching (no TV upload)
            if TARGET_URL:
                async with _status_lock:
                    _last_sync_time = datetime.now()
                    _last_sync_success = True
                    _last_error = None
                await _mqtt_update_status()

        # Calculate cycle duration and next cycle time
        cycle_end = asyncio.get_event_loop().time()
        cycle_duration = cycle_end - cycle_start
        
        # Calculate when next cycle should start (fixed interval from cycle start)
        if next_cycle_time is None:
            # First cycle: schedule next one from now
            next_cycle_time = cycle_start + INTERVAL
        else:
            # Subsequent cycles: schedule from previous target time
            next_cycle_time += INTERVAL
        
        # Calculate sleep time
        current_time = asyncio.get_event_loop().time()
        sleep_time = next_cycle_time - current_time
        
        if sleep_time > 0:
            logger.debug(f'[LOOP] Cycle #{loop_count} complete in {cycle_duration:.1f}s. Sleeping {sleep_time:.1f}s until next cycle...')
            logger.debug(f'[LOOP] ===== Cycle #{loop_count} ended =====\n')
            await asyncio.sleep(sleep_time)
        else:
            # We're running behind schedule
            logger.warning(f'[LOOP] WARNING: Cycle #{loop_count} took {cycle_duration:.1f}s (behind by {abs(sleep_time):.1f}s). Starting next cycle immediately...')
            logger.debug(f'[LOOP] ===== Cycle #{loop_count} ended =====\n')
            # Reset next_cycle_time to current time to avoid cascading delays
            next_cycle_time = current_time


async def handle_status(request):
    """API endpoint: GET /status - Returns JSON with sync status and timestamp."""
    global _last_sync_time, _last_sync_success, _last_error
    
    async with _status_lock:
        return web.json_response({
            'last_sync': _last_sync_time.isoformat() if _last_sync_time else None,
            'success': _last_sync_success,
            'error': _last_error,
            'timestamp': datetime.now().isoformat()
        })


async def handle_screenshot(request):
    """API endpoint: GET /screenshot - Returns current screenshot image."""
    try:
        if ART_PATH.exists():
            with open(str(ART_PATH), 'rb') as f:
                data = f.read()
            return web.Response(body=data, content_type='image/jpeg')
        else:
            return web.Response(status=404, text='Screenshot not yet available')
    except Exception as e:
        logger.error(f'[API] Error serving screenshot: {e}')
        return web.Response(status=500, text=f'Error: {e}')


async def start_api_server():
    """Start the aiohttp web server for status/screenshot endpoints."""
    app = web.Application()
    app.router.add_get('/status', handle_status)
    app.router.add_get('/screenshot', handle_screenshot)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    api_port = int(os.environ.get('API_PORT', '5000'))
    site = web.TCPSite(runner, '0.0.0.0', api_port)
    await site.start()
    
    logger.info(f'[API] Web server started on port {api_port}')
    logger.info(f'[API]   GET http://localhost:{api_port}/status - Sync status (JSON)')
    logger.info(f'[API]   GET http://localhost:{api_port}/screenshot - Current screenshot image')
    
    return runner


async def async_main():
    logger.debug('[STARTUP] Starting screenshot loop...')

    loop = asyncio.get_running_loop()
    
    # Initialize MQTT if enabled
    await _mqtt_connect()
    
    screenshot_task = loop.create_task(screenshot_loop())
    api_runner = await start_api_server()
    try:
        await asyncio.Event().wait()  # run indefinitely until cancelled/interrupt
    finally:
        logger.info('[SHUTDOWN] Shutting down gracefully...')
        screenshot_task.cancel()
        try:
            await screenshot_task
        except asyncio.CancelledError:
            pass
        
        # Disconnect MQTT
        await _mqtt_disconnect()
        
        # Clean up API server
        try:
            await api_runner.cleanup()
            logger.debug('[SHUTDOWN] API server stopped')
        except Exception:
            pass
        
        # Clean up persistent browser
        global _browser, _page
        if _page:
            try:
                await _page.close()
                logger.debug('[SHUTDOWN] Closed browser page')
            except Exception:
                pass
        if _browser:
            try:
                await _browser.close()
                logger.debug('[SHUTDOWN] Closed browser instance')
            except Exception:
                pass
        
        logger.debug('[SHUTDOWN] Cleanup complete')


def main():
    logger.debug('[MAIN] Starting addon...')
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info('[MAIN] Received keyboard interrupt')
    except Exception as e:
        logger.error(f'[MAIN] ERROR: Unexpected error: {e}')
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
