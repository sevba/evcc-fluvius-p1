# evcc-fluvius-p1

Docker Compose stack that connects a Belgian Fluvius smart meter (DSMR P1 port) to [EVCC](https://evcc.io) for solar-optimized EV charging, and feeds live grid energy data into Home Assistant.

## Background

Belgian Fluvius smart meters (eMUCs, based on DSMR 5.0) split grid energy across two tariff registers — `1-0:1.8.1` (day) and `1-0:1.8.2` (night) for consumption, and `1-0:2.8.1` + `1-0:2.8.2` for export. They do **not** provide a combined `1-0:1.8.0` total.

EVCC's built-in DSMR meter template can map `energy` to a single OBIS register. Because EVCC needs one combined total for its solar surplus calculation, the template alone cannot correctly represent Fluvius energy — you would get only one tariff, not the sum of both.

This stack solves that with a small custom proxy (`p1-proxy`) that reads raw DSMR telegrams, sums the tariff registers, and serves the result as a simple JSON HTTP endpoint that EVCC can consume via its `custom` meter type.

> **P1-to-LAN adapters** (e.g. HomeWizard, Slimme Lezer) have their own HTTP API and do not need ser2net or p1-proxy. This stack is specifically for **P1-to-USB cables** (FTDI-based).

## Architecture

```
Fluvius smart meter
  └─ P1 port  (DSMR 5.0, 115200 baud, RJ12)
       └─ P1-to-USB cable  (FTDI FT232R)
            └─ /dev/ttyUSB*  (host serial device)
                 └─ [ser2net]  bridges serial → TCP :3333
                      └─ [p1-proxy]  parses telegrams → HTTP :7071
                           ├─ [evcc]  EV charge controller (reads grid + PV)
                           └─ Home Assistant  (energy dashboard + sensors)
```

All four services run on the same host using `network_mode: host`, so they communicate over localhost.

## Components

### ser2net
Exposes the USB serial port as a raw TCP stream on port 3333. Any number of clients can connect simultaneously. The DSMR P1 port sends one telegram per second.

### p1-proxy
Connects to ser2net, parses incoming DSMR telegrams, and serves the latest snapshot as JSON on `http://127.0.0.1:7071/`. Returns HTTP 200 when data is available, HTTP 503 until the first telegram has been received.

Parsed OBIS codes:

| Field | OBIS code(s) | Description |
|-------|-------------|-------------|
| `power` | `1-0:1.7.0` − `1-0:2.7.0` | Net grid power in **W** (positive = consuming, negative = exporting) |
| `energy` | `1-0:1.8.1` + `1-0:1.8.2` | Total grid consumption in **kWh** (day + night tariff) |
| `energy_exp` | `1-0:2.8.1` + `1-0:2.8.2` | Total grid export in **kWh** (day + night tariff) |
| `i1` / `i2` / `i3` | `1-0:31.7.0` / `51.7.0` / `71.7.0` | Phase currents in **A** |

Example response:
```json
{"power": -451, "energy": 1520.973, "energy_exp": 1832.230, "i1": 4.17, "i2": 1.63, "i3": 6.80}
```

### evcc
EV charge controller. Reads grid data from p1-proxy and PV production from an SMA inverter via Modbus TCP. Optimizes EV charging to maximise solar self-consumption. Exposes a web UI on port 7070 and a Home Assistant integration.

## Prerequisites

- Docker and Docker Compose installed on the host
- A P1-to-USB cable plugged into the Fluvius meter RJ12 P1 port and the host USB port
- *(Optional)* An SMA inverter reachable on the local network via Modbus TCP (port 502)

## Installation

1. Clone this repo and `cd` into it:
   ```bash
   git clone https://github.com/sevba/evcc-fluvius-p1.git
   cd evcc-fluvius-p1
   ```

2. Find your P1 USB adapter's stable device path:
   ```bash
   ls /dev/serial/by-id/
   ```
   Look for an entry containing `FTDI` or `FT232`. Update the `devices:` line in `docker-compose.yml`:
   ```yaml
   devices:
     - /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_<your-serial>-if00-port0:/dev/ttyUSB0
   ```
   Using the `by-id` path ensures the mapping survives USB re-enumeration on reboot.

3. Configure your PV inverter in `evcc.yaml`. The default config assumes an SMA Sunny Boy reachable via Modbus TCP — change the `host` to match your inverter's IP:
   ```yaml
   host: 192.168.1.x
   ```
   If you have no PV inverter, remove the entire `pv` meter block and the `pv:` line under `site.meters`.

4. Start the stack:
   ```bash
   docker compose up -d
   ```

5. Verify P1 data is flowing:
   ```bash
   curl http://127.0.0.1:7071/
   ```
   You should see a JSON response with live values within a few seconds. A `503` response means p1-proxy has not yet received a telegram — check `docker logs ser2net` for errors.

6. Open the EVCC web UI at `http://<host-ip>:7070` to confirm grid and PV readings.

## Home Assistant

### EVCC integration

Install the [EVCC integration](https://docs.evcc.io/docs/integrations/home-assistant) via HACS or the built-in integration search. It connects to the EVCC API and creates entities for:

- `sensor.evcc_grid_configmeter_power` — current grid power (W)
- `sensor.evcc_grid_configmeter_energy` — total grid consumption (kWh)
- `sensor.evcc_pv_energy` — total PV production (kWh)
- `sensor.evcc_pv_power` — current PV power (W)
- and more (charging sessions, vehicle SoC, etc.)

Configure the integration with your host IP and EVCC's default port 7070.

### Return to grid sensor

The EVCC integration does not expose grid export energy. Add this to `configuration.yaml` to read it directly from p1-proxy:

```yaml
sensor:
  - platform: rest
    name: "P1 Return to Grid"
    unique_id: p1_return_to_grid
    resource: http://127.0.0.1:7071/
    value_template: "{{ value_json.energy_exp }}"
    unit_of_measurement: kWh
    device_class: energy
    state_class: total_increasing
    scan_interval: 10
```

Restart Home Assistant after adding this.

### Energy dashboard

Go to **Settings → Energy** and configure:

**Grid:**

| Field | Entity |
|-------|--------|
| Grid consumption | `sensor.evcc_grid_configmeter_energy` |
| Return to grid | `sensor.p1_return_to_grid` |

**Solar panels:**

| Field | Entity |
|-------|--------|
| Solar production | `sensor.evcc_pv_energy` |

## Troubleshooting

### `docker logs ser2net` shows `Port in use by pid 7` repeatedly

This is a UUCP serial port locking bug: ser2net locks the device on first open, then refuses its own subsequent opens. The `entrypoint` in `docker-compose.yml` already includes the `-u` flag to disable UUCP locking — if you see this error, make sure you are using the `entrypoint:` override from this repo and not the image's default entrypoint.

### `curl http://127.0.0.1:7071/` returns `503`

p1-proxy has not received a valid telegram yet. Check in order:
1. `docker logs ser2net` — should show no errors and accept connections
2. `nc 127.0.0.1 3333` — should print raw DSMR telegram lines starting with `/FLU5\...`
3. Confirm the correct USB device is mapped in `docker-compose.yml`
4. Confirm the P1 cable is firmly seated in the meter's RJ12 port
