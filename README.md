# Screenshot Frame - Home Assistant Add-on

Render Home Assistant dashboards (or any URL) with Playwright and send screenshots directly to Samsung Frame TV via WebSocket API.

## Features

- **Playwright Rendering**: Headless Chromium captures any URL as PNG with configurable resolution and zoom
- **Direct TV Upload**: Async WebSocket connection to Samsung Frame TV for instant art mode updates
- **Flexible Authentication**: Support for bearer tokens, basic auth, or custom headers for image providers
- **Screensaver Mode**: Cycle through local images at configurable intervals
- **Replace Last**: Optionally replace the previous uploaded image instead of creating new art entries
- **HTTP API**: Control screensaver and access rendered images via HTTP endpoints

## Configuration

### Image Provider

| Option | Description | Default |
|--------|-------------|---------|
| `image_provider_url` | URL to fetch image from (supports HTML rendering) | `http://homeassistant.local:5000/` |
| `image_provider_auth_type` | Authentication type: `none`, `bearer`, `basic`, `headers` | `none` |
| `image_provider_token` | Bearer token value | `""` |
| `image_provider_token_header` | Header name for token | `Authorization` |
| `image_provider_token_prefix` | Token prefix (e.g., "Bearer") | `Bearer` |
| `image_provider_username` | Username for basic auth | `""` |
| `image_provider_password` | Password for basic auth | `""` |
| `image_provider_headers` | JSON map of custom headers | `""` |

### Screenshot Settings

| Option | Description | Default |
|--------|-------------|---------|
| `screenshot_width` | Screenshot width in pixels | `1920` |
| `screenshot_height` | Screenshot height in pixels | `1080` |
| `screenshot_zoom` | Zoom percentage (10-500%) | `100` |
| `interval_seconds` | Seconds between screenshot updates | `300` |
| `http_port` | HTTP server port | `8200` |

### Samsung TV Settings

| Option | Description | Default |
|--------|-------------|---------|
| `use_local_tv` | Enable direct TV upload | `true` |
| `tv_ip` | Samsung Frame TV IP address | `""` |
| `tv_port` | TV WebSocket port | `8002` |
| `tv_matte` | Matte style: `modern`, `warm`, `cold`, `none` | `""` |
| `tv_show_after_upload` | Show image immediately after upload | `true` |
| `tv_replace_last` | Replace previous image instead of creating new entry | `false` |

### Screensaver

| Option | Description | Default |
|--------|-------------|---------|
| `screensaver_enabled` | Enable screensaver cycling | `false` |
| `screensaver_dir` | Directory containing screensaver images | `./screensaver` |
| `screensaver_interval` | Seconds between screensaver images | `60` |

## Usage

1. Add this repository to Home Assistant:
   ```
   https://github.com/dangerusty/hassio-screenshot-frame-addon
   ```

2. Install the "Screenshot Frame Addon" add-on

3. Configure your Samsung Frame TV IP address and image provider URL

4. Start the add-on

5. (Optional) Access the HTTP API:
   - `http://[host]:8200/art.jpg` - View current screenshot
   - `http://[host]:8200/screensaver/start` - Start screensaver
   - `http://[host]:8200/screensaver/stop` - Stop screensaver
   - `http://[host]:8200/screensaver/status` - Check screensaver status

## Authentication Examples

### Home Assistant Dashboard with Bearer Token

```json
{
  "image_provider_url": "http://homeassistant.local:8123/lovelace/dashboard",
  "image_provider_auth_type": "bearer",
  "image_provider_token": "your_long_lived_access_token"
}
```

### External Service with Basic Auth

```json
{
  "image_provider_url": "https://example.com/dashboard",
  "image_provider_auth_type": "basic",
  "image_provider_username": "user",
  "image_provider_password": "pass"
}
```

### Custom Headers (JSON)

```json
{
  "image_provider_url": "https://api.example.com/image",
  "image_provider_auth_type": "headers",
  "image_provider_headers": "{\"X-API-Key\": \"your-key\", \"X-Custom\": \"value\"}"
}
```

## How It Works

1. Addon periodically fetches from `image_provider_url`
2. If HTML is detected, Playwright renders it with Chromium at the configured resolution and zoom
3. Resulting image is uploaded to Samsung Frame TV via async WebSocket connection
4. TV displays the image in art mode (if `tv_show_after_upload` is true)
5. Optional: Replace the previous image to avoid filling up TV storage

## Requirements

- Samsung Frame TV (2017 or newer)
- TV must be on the same network as Home Assistant
- TV art mode must be supported and enabled

## Troubleshooting

### TV Not Connecting

- Verify TV IP address and port (usually 8002 for newer models, 8001 for older)
- Ensure TV is powered on and connected to network
- Check Home Assistant logs for connection errors

### Playwright Rendering Issues

- Increase `screenshot_zoom` if content appears too small
- Adjust `screenshot_width` and `screenshot_height` for your TV's native resolution
- Check provider URL is accessible from the add-on container

### Authentication Failures

- For Home Assistant dashboards, create a long-lived access token
- Verify auth credentials in add-on logs
- Test provider URL manually with curl/browser

## Credits

- Based on [hass-lovelace-kindle-screensaver](https://github.com/sibbl/hass-lovelace-kindle-screensaver)
- Uses [samsung-tv-ws-api](https://github.com/xchwarze/samsung-tv-ws-api) for TV communication

## License

MIT
