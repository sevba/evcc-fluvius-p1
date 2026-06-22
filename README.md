# evcc-fluvius-p1

Docker Compose stack that connects a Belgian Fluvius smart meter (DSMR P1) to [EVCC](https://evcc.io) and Home Assistant.

## Components

- **ser2net** — bridges the P1 serial port to TCP 3333
- **p1-proxy** — reads P1 telegrams from ser2net, parses OBIS codes, and serves live values as JSON on port 7071
- **evcc** — EV charge controller, reads grid power/energy/currents from p1-proxy and PV production from an SMA inverter via Modbus

> **Note:** This setup assumes a P1-to-USB cable (FTDI-based). The P1 port on the Fluvius meter outputs DSMR telegrams at 115200 baud, which ser2net reads directly from the USB serial device. P1-to-LAN adapters have their own TCP endpoint and do not need ser2net or this proxy.

## Installation

1. Clone this repo and `cd` into it.
2. Adjust the serial device path in `docker-compose.yml` if needed:
   ```yaml
   devices:
     - /dev/serial/by-id/<your-device-id>:/dev/ttyUSB0
   ```
   Run `ls /dev/serial/by-id/` to find yours.
3. Set your SMA inverter IP in `evcc.yaml`:
   ```yaml
   host: 10.0.40.19
   ```
4. Start the stack:
   ```bash
   docker compose up -d
   ```
5. Verify the P1 proxy is receiving data:
   ```bash
   curl http://127.0.0.1:7071/
   ```
   Expected output:
   ```json
   {"power": -500, "energy": 1118.891, "energy_exp": 1135.639, "i1": 2.38, "i2": 1.14, "i3": 15.21}
   ```

## Home Assistant

### Return to grid sensor

EVCC's HA integration does not expose export energy. Add the following to `configuration.yaml` to read it directly from p1-proxy:

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

Go to **Settings → Energy → Grid** and configure:

| Field | Entity |
|---|---|
| Grid consumption | `sensor.evcc_grid_configmeter_energy` |
| Return to grid | `sensor.p1_return_to_grid` |

Go to **Settings → Energy → Solar panels** and add:

| Field | Entity |
|---|---|
| Solar production | `sensor.evcc_pv_energy` |
