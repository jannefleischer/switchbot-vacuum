#!/usr/bin/env python3
"""Read-only probe of the SwitchBot cloud for vacuum task records.

Sends no device commands. Secrets are read from the esphome folder and never logged.

    python tools/probe_task_records.py <esphome-dir>
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

AUTH = "https://account.api.switchbot.net"
CLIENT_ID = "5nnwmhmsa9xxskm14hd85lm9bm"
APP_VERSION = "8.6.1"
S20_TYPES = {"W1106000", "W1107000"}
SHADOW_IDS = [1010, 1013, 1015, 1016, 1018, 1023, 1028, 1029, 1051, 1052, 1053, 1055]
SECRET_KEY = re.compile(r"token|secret|password|accesskey|credential|authorization", re.I)

base = Path(sys.argv[1])
env = dict(
    line.strip().split("=", 1)
    for line in (base / ".env").read_text(encoding="utf-8-sig").splitlines()
    if "=" in line and not line.strip().startswith("#")
)
USER = env["SWITCHBOT_USER"].strip().strip("\"'")
PASSWORD = (base / "secrets" / "switchbot_password.secret").read_text(encoding="utf-8-sig").strip("\r\n")
log_path = base / "logs" / f"probe-task-records-{time.strftime('%Y%m%d-%H%M%S')}.log"
client_uuid = str(uuid.uuid4())
token = ""


def scrub(value):
    """Return a copy with secret-looking keys masked and the account e-mail removed."""
    if isinstance(value, dict):
        return {k: "***" if SECRET_KEY.search(k) else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return value.replace(USER, "***")
    return value


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line, flush=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def post(url, body):
    headers = {
        "authorization": token,
        "uuid": client_uuid,
        "requestid": str(uuid.uuid4()),
        "appversion": APP_VERSION,
        "content-type": "application/json; charset=UTF-8",
    }
    request = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        text = exc.read()[:400].decode("utf8", "replace")
        return exc.code, {"http_error": text}


status, data = post(f"{AUTH}/account/api/v1/user/login", {
    "clientId": CLIENT_ID,
    "deviceInfo": {"deviceId": client_uuid, "deviceName": "Home Assistant", "model": "Home Assistant"},
    "grantType": "password",
    "password": PASSWORD,
    "username": USER,
    "verifyCode": "",
})
token = (data.get("body") or {}).get("access_token") or ""
log("login http", status, "ok" if token else json.dumps(scrub(data), ensure_ascii=False)[:400])
if not token:
    sys.exit(1)

_, data = post(f"{AUTH}/account/api/v1/user/userinfo", {})
region = (data.get("body") or {}).get("botRegion")
_, data = post(f"{AUTH}/admin/admin/api/v1/botregion/endpoint", {"botRegion": region})
host = next(v["host"] for v in data.get("data", []) if v["name"] == "wonderlabs")
log("region", region, "host", host)

_, data = post(f"{host}/wonder/device/v3/getdevice", {"required_type": "All"})
items = (data.get("body") or {}).get("Items", [])
for item in items:
    log("device", item.get("device_detail", {}).get("device_type"), "|", item.get("device_name"))
vac = next((i for i in items if i.get("device_detail", {}).get("device_type") in S20_TYPES), None)
if vac is None:
    log("no S20 found (W1106000/W1107000)")
    sys.exit(2)
mac = vac["device_mac"]
log("S20 Typ", vac["device_detail"]["device_type"], "product_key", vac.get("product_key"))

status, data = post(f"{host}/device/device/v1/shadow/getByIDs", {"deviceID": mac, "propertyIDs": SHADOW_IDS})
log("shadow http", status, json.dumps(scrub(data), ensure_ascii=False)[:6000])

PATH = "/sweeper/v1/taskRecord/list"
records = []
for page in range(1, 11):
    status, data = post(host + PATH, {"deviceID": mac, "pageNum": page, "pageSize": 20})
    body = data.get("data") or {}
    batch = body.get("recordList") or []
    log("page", page, "http", status, "code", data.get("resultCode"), "n", len(batch),
        "currentPage", body.get("currentPage"), "finalPage", body.get("finalPage"))
    if not batch:
        break
    new = [r for r in batch if r["taskID"] not in {x["taskID"] for x in records}]
    records.extend(new)
    if not new:
        log("page repeats, stopping")
        break
    time.sleep(0.5)

log("records", len(records), "keys", sorted({k for r in records for k in r}))
log("actions", sorted({r.get("action") for r in records}), "results", sorted({r.get("result") for r in records}),
    "sources", sorted({r.get("source") for r in records}))
log("actionParam keys", sorted({k for r in records for k in (r.get("actionParam") or {})}))
for r in records:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["timestamp"] / 1000))
    log(when, r.get("action"), r.get("result"), "clean_min", round((r.get("cleanTime") or 0) / 60000, 1),
        "area", r.get("taskArea"), json.dumps(r.get("actionParam"), ensure_ascii=False)[:360])
