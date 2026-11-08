# canweb

CAN bus diagnostic web app for a Raspberry Pi with a CAN transceiver. One
Python process, no dependencies beyond python-can, opens a page in any browser
on the network:

- **Bus**: every ID on the bus with data, count, rate and age, highlighted as
  it changes; decoded signals when a DBC is loaded.
- **Send**: a frame once or repeated at a typed interval.
- **Log**: ring buffer of the last 20000 frames, saved to CSV.
- **One tab per product** through plugins: inputs as lights, outputs as
  buttons, typed number controls, current graphs, status fields and settings.
  The page is generic; a plugin supplies names and values, so another product
  is one Python class.

Ships with the Robust IO plugin: 22 input lights, 8 output buttons with trip
state and a 60 s current graph each, both motors (typed duty, current graph),
heartbeat fields, and every setting as a typed field with the config key as
its label.

## Install on the Pi

    pip install -e tools/python            # robustio package (protocol, device class)
    pip install -e tools/canweb            # this app; add [dbc] for cantools decoding

SocketCAN once per boot (MCP2515 HAT or similar, after the overlay is in config.txt):

    sudo ip link set can0 up type can bitrate 250000

## Run

    canweb --host 0.0.0.0                  # http://<pi>:8090/
    canweb -i socketcan -c can0            # defaults
    canweb --dbc tools/robustio-node0.dbc  # decode Robust IO frames in the bus view
    canweb -i sim                          # against the firmware simulator (run_sim.sh live)
    canweb -i virtual -c x --no-plugins    # page only, no hardware
    canweb --plugin mypkg.module:MyPlugin  # add a plugin that is not installed as an entry point

Environment: `CANWEB_INTERFACE`, `CANWEB_CHANNEL`, `CANWEB_BITRATE`.

There is no login. On `0.0.0.0` anyone who can reach port 8090 can send frames
and switch outputs. Keep it on the bench network.

## Keepalive

A product plugin is told whether a browser page is connected (`client_alive`).
The Robust IO plugin runs the board's keepalive only while a page is open, so
closing the tab or losing the Pi lets the board time out to all off, the same
as the other tools.

## Writing a plugin

    from canweb.plugins import Plugin

    class MyPlugin(Plugin):
        name = "mything"           # tab name and URL
        title = "My Thing"

        def attach(self, bus):
            bus.add_listener(self.on_frame)   # every can.Message
            self.bus = bus

        def on_frame(self, msg): ...

        def state(self):
            return {"online": True, "status": "ok",
                    "lights":  [{"name": "IN1", "on": True}],
                    "buttons": [{"id": "relay", "label": "relay", "on": False}],
                    "numbers": [{"id": "speed", "label": "speed", "value": 0, "min": 0, "max": 100, "unit": "%"}],
                    "series":  [{"name": "current", "value": 1.25, "unit": "A"}],
                    "fields":  [{"name": "version", "value": "1.2"}],
                    "config":  [{"name": "timeout", "value": 500, "unit": "ms"}],
                    "actions": [{"id": "reset", "label": "reset"}]}

        def command(self, cmd, args):
            # cmd is "button" {id, on}, "number" {id, value}, "config" {name, value}, "action" {id}
            self.bus.send(0x200, b"\x01")
            return {"ok": True}

Register it with an entry point in the `canweb.plugins` group, or pass
`--plugin module:Class`. Series are sampled five times a second and graphed
over the last 60 s by the page. Number and config fields are typed, labelled
with the key name.

## Run at boot (systemd)

    [Unit]
    Description=canweb CAN diagnostic page
    After=network.target

    [Service]
    ExecStartPre=-/sbin/ip link set can0 up type can bitrate 250000
    ExecStart=/home/pi/.local/bin/canweb --host 0.0.0.0 --dbc /home/pi/robust-io/tools/robustio-node0.dbc
    Restart=on-failure
    User=root

    [Install]
    WantedBy=multi-user.target

Save as `/etc/systemd/system/canweb.service`, then `systemctl enable --now canweb`.

## API

| Call | Purpose |
|---|---|
| `GET /events` | server-sent events, a JSON frame with bus and plugin state 5 times a second |
| `GET /api/bus` | bus snapshot |
| `POST /api/send {"id":"123","data":"01 02","ext":false}` | send a frame |
| `POST /api/clear` | reset per-ID statistics |
| `POST /api/dbc {"path":...}` | load a DBC |
| `GET /api/log?limit=500`, `POST /api/log/save {"path":...}` | frame log |
| `GET /api/plugins` | installed plugins |
| `POST /api/plugin/<name> {"cmd":...,"args":{...}}` | plugin command |
