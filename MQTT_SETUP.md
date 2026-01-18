# MQTT Integration Setup

The Screenshot Frame addon now supports Home Assistant MQTT Discovery, allowing automatic sensor creation in Home Assistant.

## Configuration

Add the following environment variables to your addon's `config.yaml` or directly in Home Assistant addon settings:

### MQTT Settings

- **`MQTT_ENABLED`**: Enable/disable MQTT integration (`true`/`false`, default: `false`)
- **`MQTT_BROKER`**: MQTT broker hostname or IP (default: `localhost`)
- **`MQTT_PORT`**: MQTT broker port (default: `1883`)
- **`MQTT_USERNAME`**: MQTT broker username (optional)
- **`MQTT_PASSWORD`**: MQTT broker password (optional)
- **`MQTT_TOPIC_BASE`**: MQTT topic base for discovery (default: `homeassistant`)

### Example `docker-compose.yml` or addon configuration:

```yaml
environment:
  MQTT_ENABLED: "true"
  MQTT_BROKER: "homeassistant.local"
  MQTT_PORT: "1883"
  MQTT_USERNAME: "mqttuser"
  MQTT_PASSWORD: "mqttpassword"
```

## Sensors Created

When MQTT is enabled and connected, the addon automatically publishes and creates the following sensors in Home Assistant:

1. **Screenshot Frame Last Sync** (timestamp sensor)
   - Shows the ISO timestamp of the last successful sync
   - State topic: `screenshot_frame/last_sync`
   - Device class: `timestamp`

2. **Screenshot Frame Sync Success** (binary sensor)
   - Shows `ON` if the last sync succeeded, `OFF` if it failed
   - State topic: `screenshot_frame/success`
   - Device class: `connectivity`

3. **Screenshot Frame Last Error** (text sensor)
   - Shows the error message from the last failed sync, or `None`
   - State topic: `screenshot_frame/error`

All sensors will appear under a single device named "Screenshot Frame" in Home Assistant.

## Home Assistant Setup

Once MQTT is enabled and the addon is running:

1. Go to **Settings → Devices & Services → MQTT**
2. The Screenshot Frame device should appear automatically
3. You'll see the three sensors listed above
4. Use them in automations, templates, or dashboards

### Example Dashboard Card

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Screenshot Frame Status
    entities:
      - entity: sensor.screenshot_frame_last_sync
      - entity: binary_sensor.screenshot_frame_sync_success
      - entity: sensor.screenshot_frame_last_error
```

## Debugging

Enable `DEBUG_LOGGING=true` to see MQTT connection details in the addon logs:

```
[MQTT] Connecting to homeassistant.local:1883...
[MQTT] ✓ Connected to MQTT broker
[MQTT] Published discovery for last_sync
[MQTT] Published discovery for success
[MQTT] Published discovery for error
[MQTT] Published status update (success=True)
```

## Fallback to REST API

If MQTT is not available or disabled, the addon still provides REST endpoints:
- `GET http://addon-ip:5000/status` - JSON status
- `GET http://addon-ip:5000/screenshot` - Current screenshot image
