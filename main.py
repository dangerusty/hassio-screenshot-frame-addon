import os
import asyncio
import json
from aiohttp import web, ClientSession, BasicAuth
from pathlib import Path

# Playwright is required: import at module level so failures surface early.
from playwright.async_api import async_playwright

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
HTTP_PORT = int(os.environ.get('HTTP_PORT', 8200))
SCREENSHOT_WIDTH = int(os.environ.get('SCREENSHOT_WIDTH', '1920'))
SCREENSHOT_HEIGHT = int(os.environ.get('SCREENSHOT_HEIGHT', '1080'))
SCREENSHOT_ZOOM = int(os.environ.get('SCREENSHOT_ZOOM', '100'))  # percentage: 100 = 100%, 150 = 150%, etc.

# Local TV options (from add-on options.json exported by run.sh)
TV_IP = os.environ.get('TV_IP') or ''
TV_PORT = int(os.environ.get('TV_PORT', '8001'))
TV_MATTE = os.environ.get('TV_MATTE') or None
TV_SHOW_AFTER_UPLOAD = os.environ.get('TV_SHOW_AFTER_UPLOAD', 'true').lower() in ('1','true','yes')
IMAGE_PROVIDER_URL = os.environ.get('IMAGE_PROVIDER_URL') or os.environ.get('IMAGE_PROVIDER') or ''
# Provider auth settings (supports multiple provider types)
# IMAGE_PROVIDER_AUTH_TYPE: none|bearer|basic|headers
IMAGE_PROVIDER_AUTH_TYPE = os.environ.get('IMAGE_PROVIDER_AUTH_TYPE', 'none').lower()
IMAGE_PROVIDER_TOKEN = os.environ.get('IMAGE_PROVIDER_TOKEN')
IMAGE_PROVIDER_TOKEN_HEADER = os.environ.get('IMAGE_PROVIDER_TOKEN_HEADER', 'Authorization')
IMAGE_PROVIDER_TOKEN_PREFIX = os.environ.get('IMAGE_PROVIDER_TOKEN_PREFIX', 'Bearer')
IMAGE_PROVIDER_USERNAME = os.environ.get('IMAGE_PROVIDER_USERNAME')
IMAGE_PROVIDER_PASSWORD = os.environ.get('IMAGE_PROVIDER_PASSWORD')
IMAGE_PROVIDER_HEADERS = os.environ.get('IMAGE_PROVIDER_HEADERS')  # optional JSON map of headers

# Replace-last behavior: attempt to overwrite previous art id instead of
# creating a new stored item. When enabled the add-on will persist the
# last art id to `TV_LAST_ART_FILE` and try common replace/update APIs.
TV_REPLACE_LAST = os.environ.get('TV_REPLACE_LAST', 'false').lower() in ('1', 'true', 'yes')
TV_LAST_ART_FILE = os.environ.get('TV_LAST_ART_FILE', '/data/last-art-id.txt')


# The add-on now fetches images from an external image provider URL set by
# `IMAGE_PROVIDER_URL`. Playwright-based dashboard rendering has been removed
# to simplify the add-on: configure an image provider that exposes a JPEG/PNG
# at a reachable URL (for example the lovelace renderer at port 5000).


# Screensaver configuration
SCREENSAVER_ENABLED = os.environ.get('SCREENSAVER_ENABLED', 'false').lower() in ('1','true','yes')
SCREENSAVER_DIR = Path(os.environ.get('SCREENSAVER_DIR') or './screensaver')
SCREENSAVER_INTERVAL = int(os.environ.get('SCREENSAVER_INTERVAL', '60'))

# Ensure screensaver directory exists
try:
    SCREENSAVER_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

async def upload_image_to_tv_async(host: str, port: int, image_path: str, matte: str = None, show: bool = True):
    try:
        from samsungtvws.async_art import SamsungTVAsyncArt
    except Exception as e:
        print('samsungtvws.async_art library not available:', e)
        return None

    token_file = '/data/tv-token.txt'
    tv = None
    try:
        tv = SamsungTVAsyncArt(host=host, port=port, token_file=token_file)
        await tv.start_listening()

        supported = await tv.supported()
        if not supported:
            print('TV does not support art mode via this API')
            await tv.close()
            return None

        # read image bytes
        with open(image_path, 'rb') as f:
            data = f.read()

        file_type = os.path.splitext(image_path)[1][1:].upper() or 'JPEG'
        print(f'Uploading image to TV {host}:{port} (type={file_type})')
        content_id = None

        # If configured, try to replace the previously-uploaded art id in-place
        # so we don't create a new stored item. This is best-effort and will
        # attempt several common API signatures exposed by different
        # samsungtvws versions. If none succeed we fall back to uploading.
        if TV_REPLACE_LAST:
            try:
                if os.path.exists(TV_LAST_ART_FILE):
                    with open(TV_LAST_ART_FILE, 'r') as lf:
                        last_id = lf.read().strip()
                else:
                    last_id = None
            except Exception:
                last_id = None

            if last_id:
                print('TV_REPLACE_LAST enabled; attempting in-place replace of', last_id)
                # Try calling upload with various id kwarg names
                id_kw_names = ('content_id', 'art_id', 'image_id', 'id', 'existing_id')
                for kw in id_kw_names:
                    if content_id:
                        break
                    try:
                        kwargs = {kw: last_id, 'file_type': file_type}
                        if matte:
                            kwargs['matte'] = matte
                        content_id = await tv.upload(data, **kwargs)
                        if content_id:
                            print(f'Replaced art using upload(..., {kw}=...)')
                            break
                    except TypeError:
                        # signature mismatch — try next
                        content_id = None
                    except Exception as e:
                        print('Replace attempt via upload with', kw, 'failed:', e)

                # Try common method names like replace/update on the tv object
                if not content_id:
                    method_names = ('replace', 'update', 'replace_image', 'update_image', 'update_art')
                    for name in method_names:
                        if content_id:
                            break
                        method = getattr(tv, name, None)
                        if method and callable(method):
                            try:
                                # try (id, data, file_type)
                                res = await method(last_id, data, file_type=file_type)
                                if res:
                                    content_id = last_id
                                    print(f'Replaced art using tv.{name}(id, data, ...)')
                                    break
                            except TypeError:
                                try:
                                    # try (data, file_type, id=...)
                                    res = await method(data, file_type=file_type, id=last_id)
                                    if res:
                                        content_id = last_id
                                        print(f'Replaced art using tv.{name}(data, file_type, id=...)')
                                        break
                                except Exception:
                                    pass
                            except Exception as e:
                                print('Replace attempt via', name, 'failed:', e)

                # Try art() namespace if present (sync-style API may be proxied)
                if not content_id and hasattr(tv, 'art'):
                    try:
                        art_ns = tv.art()
                        for name in ('replace', 'update', 'upload'):
                            if content_id:
                                break
                            method = getattr(art_ns, name, None)
                            if method and callable(method):
                                try:
                                    # many art_ns methods are sync; attempt async if coroutine
                                    res = method(data, file_type=file_type, id=last_id) if name == 'upload' else method(last_id, data)
                                    # if res is awaitable, await it
                                    if asyncio.iscoroutine(res):
                                        res = await res
                                    if res:
                                        content_id = last_id if name != 'upload' else res
                                        print(f'Replaced art using art().{name}()')
                                        break
                                except TypeError:
                                    try:
                                        # try alternative signatures
                                        res = method(last_id, data, file_type)
                                        if asyncio.iscoroutine(res):
                                            res = await res
                                        if res:
                                            content_id = last_id
                                            print(f'Replaced art using art().{name}() alt')
                                            break
                                    except Exception:
                                        pass
                                except Exception as e:
                                    print('art().'+name+' failed:', e)
                    except Exception:
                        pass

                if content_id:
                    print('In-place replace succeeded; using id', content_id)

        # If replace didn't run or didn't succeed, upload as normal
        if not content_id:
            try:
                # Prefer the matte-aware signature, but fall back if not available.
                content_id = await tv.upload(data, file_type=file_type, matte=matte) if matte else await tv.upload(data, file_type=file_type)
            except TypeError:
                content_id = await tv.upload(data, file_type=file_type)

        print('Upload returned id:', content_id)
        if content_id is not None:
            try:
                # Try to select with show parameter (controls whether image is displayed)
                await tv.select_image(content_id, show=show)
                print(f'Selected uploaded image on TV (show={show})')
            except TypeError:
                # If show parameter not supported, try without it
                try:
                    await tv.select_image(content_id)
                    print('Selected uploaded image on TV (without show parameter)')
                except Exception as e:
                    print('Failed to select uploaded image:', e)
            except Exception as e:
                print('Failed to select uploaded image:', e)

        await tv.close()

        # Persist last art id for future replace attempts
        try:
            if content_id:
                with open(TV_LAST_ART_FILE, 'w') as lf:
                    lf.write(str(content_id))
        except Exception:
            pass

        return content_id
    except Exception as e:
        print('Error interacting with TV (async):', e)
        try:
            if tv:
                await tv.close()
        except Exception:
            pass
        return None


async def render_url_with_playwright(url: str, headers: dict | None = None, timeout: int = 30000, width: int = 1920, height: int = 1080, zoom: int = 100):
    """Render the given URL to a PNG using Playwright and return bytes.

    Args:
        zoom: Zoom percentage (100 = 100%, 150 = 150%, 50 = 50%)

    Raises an exception on failure so the add-on fails fast if Playwright
    cannot render. Playwright is required for this add-on's primary purpose.
    """
    async with async_playwright() as p:
        # Try launching with default args first; fall back to a no-sandbox
        # option if the browser fails to start in some environments.
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"]) 
        # deviceScaleFactor controls zoom: 1.0 = 100%, 1.5 = 150%, etc.
        device_scale_factor = zoom / 100.0
        context = await browser.new_context(
            viewport={'width': width, 'height': height},
            device_scale_factor=device_scale_factor
        )
        if headers:
            await context.set_extra_http_headers({str(k): str(v) for k, v in (headers.items() if isinstance(headers, dict) else [])})
        page = await context.new_page()
        await page.goto(url, wait_until='networkidle', timeout=timeout)
        try:
            await page.wait_for_load_state('networkidle', timeout=2000)
        except Exception:
            pass
        data = await page.screenshot(full_page=True, type='png')
        await browser.close()
        return data


async def screenshot_loop(app):
    if not IMAGE_PROVIDER_URL:
        print('No IMAGE_PROVIDER_URL configured; the add-on will only upload if this is set.')

    while True:
        try:
            if not IMAGE_PROVIDER_URL:
                print('Skipping fetch; IMAGE_PROVIDER_URL not set')
            else:
                try:
                    # Build headers/auth dynamically so the provider can be
                    # Home Assistant (token header), DakBoard (basic auth), or
                    # any other URL requiring custom headers.
                    headers = {}
                    auth = None
                    if IMAGE_PROVIDER_HEADERS:
                        try:
                            parsed = json.loads(IMAGE_PROVIDER_HEADERS)
                            if isinstance(parsed, dict):
                                headers.update(parsed)
                        except Exception:
                            print('Failed to parse IMAGE_PROVIDER_HEADERS; expecting JSON map')

                    if IMAGE_PROVIDER_AUTH_TYPE == 'bearer' and IMAGE_PROVIDER_TOKEN:
                        headers[IMAGE_PROVIDER_TOKEN_HEADER] = f"{IMAGE_PROVIDER_TOKEN_PREFIX} {IMAGE_PROVIDER_TOKEN}"
                    elif IMAGE_PROVIDER_AUTH_TYPE == 'basic' and IMAGE_PROVIDER_USERNAME and IMAGE_PROVIDER_PASSWORD:
                        auth = BasicAuth(IMAGE_PROVIDER_USERNAME, IMAGE_PROVIDER_PASSWORD)

                    async with ClientSession() as session:
                        print(f'Fetching image from provider: {IMAGE_PROVIDER_URL} (auth={IMAGE_PROVIDER_AUTH_TYPE})')
                        async with session.get(IMAGE_PROVIDER_URL, timeout=30, headers=headers or None, auth=auth) as resp:
                            if resp.status == 200:
                                ctype = (resp.headers.get('content-type') or '').lower()
                                content = await resp.read()
                                # If the provider returns HTML, render it with Playwright
                                if ctype.startswith('text/html') or (len(content) > 0 and content.lstrip().startswith(b'<')):
                                    print('Provider returned HTML; attempting Playwright render')
                                    rendered = await render_url_with_playwright(IMAGE_PROVIDER_URL, headers=headers, width=SCREENSHOT_WIDTH, height=SCREENSHOT_HEIGHT, zoom=SCREENSHOT_ZOOM)
                                    if rendered:
                                        with open(str(ART_PATH), 'wb') as f:
                                            f.write(rendered)
                                        print('Saved Playwright-rendered image to', ART_PATH)
                                    else:
                                        # Fallback: save the raw response (likely HTML) for debugging
                                        with open(str(ART_PATH), 'wb') as f:
                                            f.write(content)
                                        print('Playwright not available or failed; saved raw provider response to', ART_PATH)
                                else:
                                    with open(str(ART_PATH), 'wb') as f:
                                        f.write(content)
                                    print('Saved image from provider to', ART_PATH)
                            else:
                                print('Image provider returned status', resp.status)
                except Exception as e:
                    print('Error fetching image from provider:', e)
        except Exception as e:
            print('Fetch loop error:', e)

        if TV_IP:
            try:
                content_id = await upload_image_to_tv_async(TV_IP, TV_PORT, str(ART_PATH), TV_MATTE, TV_SHOW_AFTER_UPLOAD)
                if not content_id:
                    print('Async upload returned no id; upload may have failed or TV returned no id')
            except Exception as e:
                print('Local TV upload error:', e)
        else:
            print('Local TV not configured; skipping upload (set use_local_tv and tv_ip).')

        await asyncio.sleep(INTERVAL)


async def get_screensaver_images():
    images = []
    try:
        for p in SCREENSAVER_DIR.iterdir():
            if p.is_file() and p.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                images.append(str(p))
    except Exception:
        pass
    images.sort()
    return images


async def screensaver_loop(app):
    images = await get_screensaver_images()
    if not images:
        print('Screensaver enabled but no images in', SCREENSAVER_DIR)
    idx = 0
    print('Screensaver loop started; cycling images every', SCREENSAVER_INTERVAL, 's')
    try:
        while True:
            images = await get_screensaver_images()
            if not images:
                await asyncio.sleep(SCREENSAVER_INTERVAL)
                continue

            img = images[idx % len(images)]
            try:
                print('Screensaver uploading', img)
                content_id = await upload_image_to_tv_async(TV_IP, TV_PORT, img, TV_MATTE, True)
                if not content_id:
                    print('Async screensaver upload returned no id for', img)
            except Exception as e:
                print('Screensaver upload error:', e)

            idx += 1
            await asyncio.sleep(SCREENSAVER_INTERVAL)
    except asyncio.CancelledError:
        print('Screensaver loop cancelled')
    except Exception as e:
        print('Screensaver loop error:', e)


async def handle_screensaver_start(request):
    app = request.app
    if app.get('screensaver_task'):
        return web.json_response({'status': 'already_running'})
    if not TV_IP:
        return web.json_response({'status': 'tv_not_configured'}, status=400)
    task = asyncio.create_task(screensaver_loop(app))
    app['screensaver_task'] = task
    return web.json_response({'status': 'started'})


async def handle_screensaver_stop(request):
    app = request.app
    task = app.get('screensaver_task')
    if not task:
        return web.json_response({'status': 'not_running'})
    task.cancel()
    try:
        await task
    except Exception:
        pass
    app['screensaver_task'] = None
    return web.json_response({'status': 'stopped'})


async def handle_screensaver_status(request):
    app = request.app
    running = bool(app.get('screensaver_task'))
    images = await get_screensaver_images()
    return web.json_response({'running': running, 'image_count': len(images)})


async def handle_screensaver_upload(request):
    reader = await request.multipart()
    saved = []
    # accept multiple files
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.filename:
            filename = os.path.basename(part.filename)
            dest = SCREENSAVER_DIR / filename
            with open(dest, 'wb') as f:
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)
            saved.append(str(dest))
    return web.json_response({'saved': saved})


async def handle_art(request):
    if not ART_PATH.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path=str(ART_PATH))


async def init_app():
    app = web.Application()
    app.router.add_get('/art.jpg', handle_art)
    # screensaver control endpoints
    app.router.add_post('/screensaver/start', handle_screensaver_start)
    app.router.add_post('/screensaver/stop', handle_screensaver_stop)
    app.router.add_get('/screensaver/status', handle_screensaver_status)
    app.router.add_post('/screensaver/upload', handle_screensaver_upload)
    app['screensaver_task'] = None
    return app


def main():
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(init_app())
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, '0.0.0.0', HTTP_PORT)
    loop.run_until_complete(site.start())
    print(f'HTTP server running on 0.0.0.0:{HTTP_PORT} serving /art.jpg')
    # start screenshot loop
    loop.create_task(screenshot_loop(app))
    # start screensaver loop if enabled
    if SCREENSAVER_ENABLED and TV_IP:
        app_task = loop.create_task(screensaver_loop(app))
        app['screensaver_task'] = app_task
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
