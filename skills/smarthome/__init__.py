"""Smart home skill — Zigbee2MQTT via MQTT."""
from __future__ import annotations
import json
import logging
import threading
import time

log = logging.getLogger(__name__)

TOOLS = [
    {"name": "smarthome_control",
     "description": "Control a smart home device (lights, switches, locks, thermostats) via Zigbee2MQTT.",
     "input_schema": {"type": "object", "properties": {
         "device": {"type": "string", "description": "Device friendly name e.g. 'living_room_light'"},
         "action": {"type": "string", "description": "on|off|toggle|brightness|color_temp|color|lock|unlock|set_temp"},
         "value": {"description": "Value for action (brightness 0-254, hex color, temp °F)"}},
         "required": ["device", "action"]}},
    {"name": "smarthome_query",
     "description": "Get the current state of a smart home device.",
     "input_schema": {"type": "object", "properties": {
         "device": {"type": "string", "description": "Device friendly name"}},
         "required": ["device"]}},
    {"name": "smarthome_list_devices",
     "description": "List all Zigbee2MQTT devices and their friendly names. Call this FIRST to get exact device names before controlling or querying them.",
     "input_schema": {"type": "object", "properties": {}}},
]

_ACTIONS = {"on": {"state": "ON"}, "off": {"state": "OFF"}, "toggle": {"state": "TOGGLE"},
            "lock": {"state": "LOCK"}, "unlock": {"state": "UNLOCK"}}


def _make(broker: str, port: int):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        def _no(**_): return {"error": "paho-mqtt not installed"}
        return [_no, _no]

    def _pub(topic, payload):
        try:
            c = mqtt.Client(); c.connect(broker, port, 5); c.publish(topic, json.dumps(payload)); c.disconnect()
            return True
        except Exception as e:
            log.error("MQTT publish: %s", e); return False

    def _read(topic, timeout=2.0):
        result = [None]; ev = threading.Event()
        def on_msg(c, u, m):
            try: result[0] = json.loads(m.payload)
            except: result[0] = {"raw": m.payload.decode(errors="replace")}
            ev.set()
        try:
            c = mqtt.Client(); c.on_message = on_msg; c.connect(broker, port, 5)
            c.subscribe(topic); c.loop_start(); ev.wait(timeout); c.loop_stop(); c.disconnect()
        except Exception as e: log.error("MQTT read: %s", e)
        return result[0]

    def control(device: str, action: str, value=None) -> dict:
        a = action.lower()
        if a in _ACTIONS: payload = dict(_ACTIONS[a])
        elif a == "brightness": payload = {"brightness": int(value) if value else 128}
        elif a == "color_temp": payload = {"color_temp": int(value) if value else 250}
        elif a == "color": payload = {"color": {"hex": str(value)}} if value else {}
        elif a == "set_temp": payload = {"occupied_heating_setpoint": float(value)} if value else {}
        else: payload = {a: value}
        ok = _pub(f"zigbee2mqtt/{device}/set", payload)
        return {"sent": ok, "device": device, "payload": payload}

    def query(device: str) -> dict:
        _pub(f"zigbee2mqtt/{device}/get", {"state": ""})
        time.sleep(0.3)
        state = _read(f"zigbee2mqtt/{device}")
        if state is None: return {"error": f"No response from '{device}'"}
        return {"device": device, "state": state}

    def list_devices() -> dict:
        data = _read("zigbee2mqtt/bridge/devices", timeout=3.0)
        if data is None:
            return {"error": "No response from zigbee2mqtt bridge"}
        devices = []
        for d in data if isinstance(data, list) else []:
            if d.get("type") == "Coordinator":
                continue
            devices.append({
                "name": d.get("friendly_name", "unknown"),
                "type": d.get("definition", {}).get("description", d.get("type", "")),
            })
        return {"devices": devices}

    return [control, query, list_devices]


def build(cfg) -> list[tuple[dict, object]]:
    fns = _make(cfg.mqtt_broker, cfg.mqtt_port)
    return list(zip(TOOLS, fns))
