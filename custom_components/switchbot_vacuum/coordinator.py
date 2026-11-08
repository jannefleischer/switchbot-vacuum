"""Data update coordinator for SwitchBot Vacuum."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import uuid
import zipfile
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .clean_history import last_task_summary, merge_records, room_activity
from .const import (
    API_AUTH_HOST,
    API_TIMEOUT,
    APP_VERSION,
    CLIENT_ID,
    CMD_CHANGE_MODE,
    CONF_CACHED_ROOMS,
    CONF_DEVICE_MAC,
    CONF_PASSWORD,
    CONF_PRODUCT_KEY,
    CONF_USERNAME,
    DEFAULT_S3_BUCKET,
    DEVICE_TYPE_K10,
    DEVICE_TYPE_K10PRO,
    DOMAIN,
    K10_WORK_STATUS_STANDBY,
    K10PRO_PROP_AUTO_RESTART,
    K10PRO_PROP_BATTERY,
    K10PRO_PROP_CHILD_LOCK,
    K10PRO_PROP_DUST_COLECT_FREQUENCY,
    K10PRO_PROP_DUST_COLECT_TIME,
    K10PRO_PROP_ONLINE,
    K10PRO_PROP_SUCTION_POW_LEVEL,
    K10PRO_PROP_WORK_STATUS,
    IDLE_WORK_STATUSES,
    MAP_MIN_REFRESH_SECONDS,
    MAP_RETRY_SECONDS,
    MAP_SAFETY_REFRESH_SECONDS,
    PROP_LAST_TASK_ID,
    PROP_TASK_TYPE,
    UPDATE_INTERVAL_IDLE_SECONDS,
    PROP_AWS_CREDS,
    PROP_BATTERY,
    PROP_CLEAN_MODE,
    PROP_CLEAN_SUMMARY,
    PROP_ERROR_CODE,
    PROP_FIRMWARE,
    PROP_MAP_ID,
    PROP_MAP_INFO,
    PROP_ONLINE,
    PROP_ROOM_PLANS,
    PROP_S3_BUCKET,
    PROP_S3_OBJECT,
    PROP_WORK_STATUS,
    S3_REGION,
    SUPPORTED_DEVICE_TYPES,
    HISTORY_FOLLOWUP_SECONDS,
    HISTORY_FOLLOWUP_WINDOW_SECONDS,
    HISTORY_SAFETY_REFRESH_SECONDS,
    TOKEN_REFRESH_SECONDS,
    UPDATE_INTERVAL_SECONDS,
)
from .map import MAP_FILES, SwitchBotMap, parse_map

_LOGGER = logging.getLogger(__name__)

STATUS_PROPS = [PROP_ONLINE, PROP_BATTERY, PROP_WORK_STATUS, PROP_ERROR_CODE,
                PROP_CLEAN_MODE, PROP_CLEAN_SUMMARY, PROP_FIRMWARE,
                PROP_TASK_TYPE, PROP_LAST_TASK_ID, PROP_MAP_INFO]
K10PRO_STATUS_PROPS = [
    K10PRO_PROP_ONLINE,
    K10PRO_PROP_BATTERY,
    K10PRO_PROP_SUCTION_POW_LEVEL,
    K10PRO_PROP_WORK_STATUS,
    K10PRO_PROP_DUST_COLECT_FREQUENCY,
    K10PRO_PROP_CHILD_LOCK,
    K10PRO_PROP_DUST_COLECT_TIME,
    K10PRO_PROP_AUTO_RESTART,
]


def _first_error_code(raw: Any) -> int:
    """Normalize the error code property, which some firmwares report as a list."""
    if isinstance(raw, list):
        codes = [code for code in raw if isinstance(code, int) and code != 0]
        return codes[0] if codes else 0
    return raw if isinstance(raw, int) else 0


class SwitchBotS10Coordinator(DataUpdateCoordinator):
    """Manage fetching data from SwitchBot Vacuum API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.access_token: str | None = None
        self.bot_region: str | None = None
        self.wonderlab_endpoint: str | None = None
        self.device_mac: str | None = None
        self.device_name: str | None = None
        self.user_id: str | None = None
        self._uuid: str = str(uuid.uuid4())
        self._token_expiry: float = 0
        # Restore rooms from the options cache so they survive HA restarts. The config
        # flow builds a coordinator before an entry exists, so there is nothing to
        # restore in that case.
        cached: Any = entry.options.get(CONF_CACHED_ROOMS, {}) if entry else {}
        self._rooms: dict[str, str] = cached if isinstance(cached, dict) else {}
        self._last_room_refresh: float = 0
        self._map: SwitchBotMap | None = None
        self._last_map_refresh: float = 0
        self._tasks: dict[str, dict[str, Any]] = {}
        self._history_loaded: bool = False
        self._last_history_refresh: float = 0
        self._history_key: tuple[Any, Any] | None = None
        self._history_followup_until: float = 0
        self._map_fingerprint: str | None = None
        self._history_store: Store | None = (
            Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.task_history") if entry else None
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )

    def _is_k10(self) -> bool:
        """Return True if device is K10+."""
        return self.entry.data.get("device_type") == DEVICE_TYPE_K10

    def _is_k10_pro(self) -> bool:
        """Return True if device is K10+."""
        return self.entry.data.get("device_type") == DEVICE_TYPE_K10PRO

    def _headers(self, auth: str | None = None) -> dict[str, str]:
        """Build common request headers."""
        return {
            "authorization": auth if auth is not None else (self.access_token or ""),
            "uuid": self._uuid,
            "requestid": str(uuid.uuid4()),
            "appversion": APP_VERSION,
            "content-type": "application/json; charset=UTF-8",
        }

    async def async_login(self) -> None:
        """Authenticate with SwitchBot API."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{API_AUTH_HOST}/account/api/v1/user/login",
                headers=self._headers(auth=""),
                json={
                    "clientId": CLIENT_ID,
                    "deviceInfo": {
                        "deviceId": self._uuid,
                        "deviceName": "Home Assistant",
                        "model": "Home Assistant",
                    },
                    "grantType": "password",
                    "password": self.entry.data[CONF_PASSWORD],
                    "username": self.entry.data[CONF_USERNAME],
                    "verifyCode": "",
                },
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                data = await resp.json()
                body = data.get("body", {})
                token = body.get("access_token")
                if not token:
                    raise ConfigEntryAuthFailed(
                        f"Login failed: {data.get('message', data.get('statusCode', 'unknown'))}"
                    )
                self.access_token = token
                self._token_expiry = time.time() + TOKEN_REFRESH_SECONDS
            async with session.post(
                f"{API_AUTH_HOST}/account/api/v1/user/userinfo",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                data = await resp.json()
                body = data.get("body", {})
                self.bot_region = body.get("botRegion")
                if not self.bot_region:
                    raise ConfigEntryAuthFailed(
                        f"Get UserInfo failed: {data.get('message', data.get('statusCode', 'unknown'))}"
                    )
            async with session.post(
                f"{API_AUTH_HOST}/admin/admin/api/v1/botregion/endpoint",
                headers=self._headers(),
                json={
                    "botRegion": self.bot_region,
                },
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                data = await resp.json()
                body = data.get("data", [])
                self.wonderlab_endpoint = next(
                    (v["host"] for v in body if v["name"] == "wonderlabs"), None
                )
                if not self.wonderlab_endpoint:
                    raise ConfigEntryAuthFailed(
                        f"Get Endpoints failed: {data.get('message', data.get('resultCode', 'unknown'))}"
                    )

    async def async_discover_devices(self) -> list[dict[str, Any]]:
        """Find all supported vacuum devices in the account."""
        async with aiohttp.ClientSession() as session, session.post(
            f"{self.wonderlab_endpoint}/wonder/device/v3/getdevice",
            headers=self._headers(),
            json={"required_type": "All"},
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            data = await resp.json()
            devices = []
            for device in data.get("body", {}).get("Items", []):
                device_type = device.get("device_detail", {}).get("device_type")
                if device_type in SUPPORTED_DEVICE_TYPES:
                    devices.append({
                        "device_mac": device["device_mac"],
                        "device_name": device.get("device_name", "SwitchBot Vacuum"),
                        "device_type": device_type,
                        "product_key": device.get("product_key", ""),
                        "user_id": device.get("userID"),
                        "group_id": device.get("groupID"),
                    })
            return devices

    def set_device(self, device_mac: str, device_name: str, user_id: str | None = None) -> None:
        """Set the target device after config flow discovery."""
        self.device_mac = device_mac
        self.device_name = device_name
        self.user_id = user_id

    async def async_get_properties(self, property_ids: list[int]) -> dict[int, Any]:
        """Fetch device properties from shadow API (S10 only)."""
        async with aiohttp.ClientSession() as session, session.post(
            f"{self.wonderlab_endpoint}/device/device/v1/shadow/getByIDs",
            headers=self._headers(),
            json={"deviceID": self.device_mac, "propertyIDs": property_ids},
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            data = await resp.json()
            if data.get("resultCode") != 100:
                raise UpdateFailed(f"Property fetch failed: {data}")
            result = {}
            for pid_str, prop in (data.get("data") or {}).items():
                result[int(pid_str)] = prop.get("value")
            return result

    async def async_send_command(
        self, function_id: int, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a command to the device via invokeFunc (S10 only)."""
        async with aiohttp.ClientSession() as session, session.post(
            f"{self.wonderlab_endpoint}/command/cmd/api/v1/func/invoke",
            headers=self._headers(),
            json={
                "deviceID": self.device_mac,
                "functionID": function_id,
                "params": params,
                "notify": {
                    "type": "mqtt",
                    "url": f"v1_1/{self._uuid}/APP_HA_{self._uuid}/funcResp",
                },
                "optSrc": "app",
                "timeout": 65535,
            },
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            return await resp.json()

    def current_clean_mode(self) -> dict[str, Any]:
        """Return the active clean mode, falling back to device defaults."""
        mode = self.data.get("clean_mode", {}) if self.data else {}
        if not isinstance(mode, dict):
            mode = {}
        return {
            "fan_level": mode.get("fan_level", 1),
            "times": mode.get("times", 1),
            "type": mode.get("type", "sweep_mop"),
            "water_level": mode.get("water_level", 1),
        }

    async def async_change_clean_mode(self, **overrides: Any) -> dict[str, Any]:
        """Send a full clean mode, replacing only the given fields.

        Function 1043 replaces the whole mode object, so unchanged fields have to be
        sent back alongside the ones being changed.
        """
        mode = self.current_clean_mode() | {
            k: v for k, v in overrides.items() if v is not None
        }
        result = await self.async_send_command(CMD_CHANGE_MODE, {"0": mode})
        # Reflect the change immediately; the shadow can lag a poll behind.
        self.async_set_updated_data((self.data or {}) | {"clean_mode": mode})
        await self.async_request_refresh()
        return result

    async def _get_product_key(self) -> str:
        """Return product_key from config entry or re-discover it."""
        key = self.entry.data.get(CONF_PRODUCT_KEY, "")
        if key:
            return key
        _LOGGER.info("product_key missing from config, re-discovering devices")
        devices = await self.async_discover_devices()
        for device in devices:
            if device["device_mac"] == self.device_mac:
                key = device.get("product_key", "")
                if key:
                    _LOGGER.info("Found product_key for %s: %s", self.device_mac, key)
                break
        return key

    async def async_send_action(
        self, identifier: str, input_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a command to K10+ via setAction."""
        product_key = await self._get_product_key()
        async with aiohttp.ClientSession() as session, session.post(
            f"{self.wonderlab_endpoint}/wonder/sweeper360/v1/device/setAction",
            headers=self._headers(),
            json={
                "productKey": product_key,
                "deviceName": self.device_mac,
                "identifier": identifier,
                "input": input_data or {},
            },
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            return await resp.json()

    async def async_send_info(self, items: dict[str, Any]) -> dict[str, Any]:
        """Set K10+ device properties via setInfo endpoint."""
        product_key = await self._get_product_key()
        async with aiohttp.ClientSession() as session, session.post(
            f"{self.wonderlab_endpoint}/wonder/sweeper360/v1/device/setInfo",
            headers=self._headers(),
            json={
                "productKey": product_key,
                "deviceName": self.device_mac,
                "items": items,
            },
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            return await resp.json()

    async def async_get_k10_status(self) -> dict[str, Any]:
        """Fetch real-time K10+ status via getstatus endpoint."""
        async with aiohttp.ClientSession() as session, session.post(
            f"{self.wonderlab_endpoint}/wonder/devicestatus/v1/getstatus",
            headers=self._headers(),
            json={"items": [self.device_mac]},
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            data = await resp.json()
            if data.get("statusCode") != 100:
                raise UpdateFailed(f"K10+ getstatus failed: {data}")
            items = data.get("body", {}).get("items", [])
            if not items:
                raise UpdateFailed("K10+ getstatus returned no items")
            return items[0]

    async def async_refresh_k10_rooms(self) -> None:
        """Fetch K10+ room IDs from GetCleanPolicyList and build room map."""
        try:
            resp = await self.async_send_action("GetCleanPolicyList")
            if resp.get("statusCode") != 100:
                _LOGGER.warning("GetCleanPolicyList failed: %s", resp)
                return

            result = json.loads(resp["body"]["result"])
            policy = json.loads(result["CleanPolicyList"])

            room_ids: set[int] = set()
            for entry in policy.get("value", []):
                for rid in entry.get("smartAreaIds", []):
                    room_ids.add(rid)

            if room_ids:
                self._rooms = {f"room{rid}": f"room{rid}" for rid in sorted(room_ids)}
                self._last_room_refresh = time.time()
                self._persist_rooms()
                _LOGGER.info("Loaded %d K10+ rooms: %s", len(self._rooms), list(self._rooms))
        except Exception as exc:
            _LOGGER.warning("Failed to refresh K10+ rooms: %s", exc)

    def _extract_rooms_from_room_plans(self, room_plans: Any) -> dict[str, str]:
        """Try to extract room names from PROP_ROOM_PLANS property."""
        rooms: dict[str, str] = {}
        if not room_plans:
            return rooms
        plans = room_plans if isinstance(room_plans, list) else []
        if isinstance(room_plans, dict):
            plans = room_plans.get("data", room_plans.get("rooms", []))
        for room in plans:
            if not isinstance(room, dict):
                continue
            room_id = str(room.get("id", room.get("roomId", "")))
            name = room.get("name", room.get("roomName", room_id))
            if room_id.startswith("ROOM_"):
                rooms[room_id] = name
        return rooms

    def _s3_client(self, creds: dict[str, Any]) -> Any:
        """Return an aiobotocore S3 client using the device's temporary credentials."""
        import aiobotocore.session

        return aiobotocore.session.get_session().create_client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id=creds["accessKeyId"],
            aws_secret_access_key=creds["secretAccessKey"],
            aws_session_token=creds["sessionToken"],
        )

    def _download_s3_objects(
        self, creds: dict[str, Any], bucket: str, keys: list[str]
    ) -> dict[str, bytes]:
        """Download objects on a worker thread, as botocore does blocking file I/O."""

        async def _download() -> dict[str, bytes]:
            objects: dict[str, bytes] = {}
            async with self._s3_client(creds) as s3:
                for key in keys:
                    try:
                        resp = await s3.get_object(Bucket=bucket, Key=key)
                    except s3.exceptions.ClientError:
                        _LOGGER.debug("S3 object not present: %s", key)
                        continue
                    objects[key] = await resp["Body"].read()
            return objects

        return asyncio.run(_download())

    async def async_fetch_map(self) -> SwitchBotMap | None:
        """Download and decode the current map package from S3 (S10 family only)."""
        props = await self.async_get_properties(
            [PROP_AWS_CREDS, PROP_S3_BUCKET, PROP_S3_OBJECT, PROP_MAP_ID]
        )
        creds = props.get(PROP_AWS_CREDS)
        prefix = props.get(PROP_S3_OBJECT)
        map_id = props.get(PROP_MAP_ID)
        bucket = props.get(PROP_S3_BUCKET) or DEFAULT_S3_BUCKET

        if not isinstance(creds, dict) or not prefix or not map_id:
            _LOGGER.debug("Map not available yet (prefix=%s, map_id=%s)", prefix, map_id)
            return None

        if creds.get("expiration", 0) < time.time():
            _LOGGER.debug("AWS credentials expired, skipping map download")
            return None

        keys = {name: f"{prefix}/{map_id}/{name}" for name in MAP_FILES}
        objects = await self.hass.async_add_executor_job(
            self._download_s3_objects, creds, bucket, list(keys.values())
        )
        files = {name: objects[key] for name, key in keys.items() if key in objects}

        return parse_map(files)

    async def async_get_task_records(self) -> list[dict[str, Any]]:
        """Fetch the cleaning task records the app shows (S10 family only)."""
        async with aiohttp.ClientSession() as session, session.post(
            f"{self.wonderlab_endpoint}/sweeper/v1/taskRecord/list",
            headers=self._headers(),
            json={"deviceID": self.device_mac, "pageNum": 1, "pageSize": 20},
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            data = await resp.json()
        if data.get("resultCode") != 200:
            raise ValueError(f"task records failed (resultCode {data.get('resultCode')})")
        return (data.get("data") or {}).get("recordList") or []

    def _history_refresh_due(self, key: tuple[Any, Any], now: float) -> bool:
        """Decide whether the task records are worth fetching.

        The record list cannot be queried incrementally, so calls are avoided instead:
        fetch when a task starts or ends, follow up briefly in case its record appears
        late, and otherwise only do a rare safety refresh.
        """
        if key != self._history_key:
            self._history_key = key
            self._history_followup_until = now + HISTORY_FOLLOWUP_WINDOW_SECONDS
            return True
        age = now - self._last_history_refresh
        if now < self._history_followup_until:
            return age >= HISTORY_FOLLOWUP_SECONDS
        return age >= HISTORY_SAFETY_REFRESH_SECONDS

    async def _async_refresh_history(self, props: dict[int, Any]) -> None:
        """Merge new task records into the persistent store.

        A failure must never break status updates, so it only keeps the stored data.
        """
        if self._history_store is None:
            return
        if not self._history_loaded:
            stored = await self._history_store.async_load()
            self._tasks = stored if isinstance(stored, dict) else {}
            self._history_loaded = True

        now = time.time()
        key = (props.get(PROP_LAST_TASK_ID), props.get(PROP_TASK_TYPE))
        if not self._history_refresh_due(key, now):
            return

        self._last_history_refresh = now
        try:
            records = await self.async_get_task_records()
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError) as exc:
            _LOGGER.debug("Task record refresh failed (%s)", type(exc).__name__)
            return
        self._tasks, changed = merge_records(self._tasks, records)
        if changed:
            await self._history_store.async_save(self._tasks)

    def _map_refresh_due(self, map_info: Any, now: float) -> bool:
        """Download the map only when its metadata changed, or as a rare retry."""
        fingerprint = json.dumps(map_info, sort_keys=True, default=str)
        age = now - self._last_map_refresh
        if fingerprint != self._map_fingerprint:
            if age < MAP_MIN_REFRESH_SECONDS:
                return False
            self._map_fingerprint = fingerprint
            self._last_room_refresh = 0
            return True
        if self._map is None:
            return age >= MAP_RETRY_SECONDS
        return age >= MAP_SAFETY_REFRESH_SECONDS

    async def _background_map_refresh(self) -> None:
        """Refresh the map in the background so it doesn't block coordinator updates."""
        self._last_map_refresh = time.time()
        try:
            self._map = await self.async_fetch_map()
            self.async_update_listeners()
        except Exception:
            _LOGGER.debug("Background map refresh failed", exc_info=True)

    @property
    def map(self) -> SwitchBotMap | None:
        """Return the most recently downloaded map."""
        return self._map

    async def async_refresh_rooms(self) -> None:
        """Refresh rooms — branches per device type."""
        if self._is_k10() or self._is_k10_pro():
            await self.async_refresh_k10_rooms()
            return

        # S10: download map from S3
        try:
            props = await self.async_get_properties(
                [PROP_MAP_INFO, PROP_AWS_CREDS, PROP_S3_BUCKET, PROP_ROOM_PLANS]
            )
        except UpdateFailed:
            _LOGGER.warning("Failed to fetch map properties for room refresh")
            return

        room_plans = props.get(PROP_ROOM_PLANS)
        rooms_from_plans = self._extract_rooms_from_room_plans(room_plans)
        if rooms_from_plans:
            self._rooms = rooms_from_plans
            self._last_room_refresh = time.time()
            self._persist_rooms()
            _LOGGER.info("Loaded %d rooms from room plans property", len(rooms_from_plans))
            return

        creds = props.get(PROP_AWS_CREDS)
        map_info = props.get(PROP_MAP_INFO)
        bucket = props.get(PROP_S3_BUCKET, DEFAULT_S3_BUCKET)

        if not creds or not isinstance(creds, dict):
            _LOGGER.warning("No AWS credentials in property %s", PROP_AWS_CREDS)
            return

        if creds.get("expiration", 0) < time.time():
            _LOGGER.debug("AWS credentials expired, skipping S3 map download")
            return

        resource = None
        if isinstance(map_info, dict):
            resource = map_info.get("resource")

        if not resource:
            _LOGGER.warning("No map resource path found")
            return

        try:
            objects = await self.hass.async_add_executor_job(
                self._download_s3_objects, creds, bucket, [resource]
            )
            zip_bytes = objects[resource]
        except Exception as exc:
            _LOGGER.warning("Failed to download map from S3: %s", exc)
            return

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                if "labels.json" in zf.namelist():
                    labels = json.loads(zf.read("labels.json"))
                    rooms = {}
                    for room in labels.get("data", []):
                        room_id = room.get("id", "")
                        name = room.get("name", room_id)
                        if room_id.startswith("ROOM_"):
                            rooms[room_id] = name
                    self._rooms = rooms
                    self._last_room_refresh = time.time()
                    self._persist_rooms()
                    _LOGGER.info("Loaded %d rooms from map", len(rooms))
        except Exception as exc:
            _LOGGER.warning("Failed to parse map zip: %s", exc)

    def _persist_rooms(self) -> None:
        """Save the current room map to config entry options so it survives restarts."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, CONF_CACHED_ROOMS: self._rooms},
        )

    async def _background_room_refresh(self) -> None:
        """Refresh rooms in the background so it doesn't block coordinator updates."""
        try:
            await self.async_refresh_rooms()
            if self._rooms:
                self.async_set_updated_data(self.data | {"rooms": self._rooms})
        except Exception:
            _LOGGER.debug("Background room refresh failed", exc_info=True)

    @property
    def rooms(self) -> dict[str, str]:
        """Return room ID to name mapping."""
        return self._rooms

    async def _ensure_token(self) -> None:
        """Refresh token if needed."""
        if not self.access_token or time.time() >= self._token_expiry:
            await self.async_login()

    async def _async_update_data_k10(self) -> dict[str, Any]:
        """Fetch real-time status data from K10+ via getstatus."""
        status = await self.async_get_k10_status()

        if time.time() - self._last_room_refresh > 86400:
            self.hass.async_create_task(self._background_room_refresh())

        return {
            "online": status.get("online_status") == "online",
            "battery": status.get("BatteryLevel", 0),
            "work_status": status.get("WorkingStatus", K10_WORK_STATUS_STANDBY),
            "error_code": 0,
            "clean_mode": {
                "fan_level": status.get("SuctionPowLevel", 1),
                "type": "sweep",
                "times": 1,
                "water_level": 1,
            },
            "clean_summary": {},
            "firmware": "",
            "rooms": self._rooms,
        }

    async def _async_update_data_k10_pro(self) -> dict[str, Any]:
        """Fetch real-time status data from K10+ Pro via getstatus."""

        if time.time() - self._last_room_refresh > 86400:
            self.hass.async_create_task(self._background_room_refresh())

        props = await self.async_get_properties(K10PRO_STATUS_PROPS)

        return {
            "online": props.get(K10PRO_PROP_ONLINE, 1) == 1,
            "battery": props.get(K10PRO_PROP_BATTERY, 0),
            "work_status": props.get(K10PRO_PROP_WORK_STATUS, 0),
            "error_code": 0,
            "clean_mode": {
                "fan_level": props.get(K10PRO_PROP_SUCTION_POW_LEVEL, 1),
                "type": "sweep",
                "times": 1,
                "water_level": 1,
            },
            "clean_summary": {},
            "firmware": "",
            "rooms": self._rooms,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch status data from device."""
        await self._ensure_token()

        if not self.device_mac:
            self.device_mac = self.entry.data.get(CONF_DEVICE_MAC)

        if self._is_k10():
            return await self._async_update_data_k10()

        if self._is_k10_pro():
            return await self._async_update_data_k10_pro()

        props = await self.async_get_properties(STATUS_PROPS)

        if time.time() - self._last_room_refresh > 86400:
            self.hass.async_create_task(self._background_room_refresh())

        if self._map_refresh_due(props.get(PROP_MAP_INFO), time.time()):
            self.hass.async_create_task(self._background_map_refresh())

        work_status = props.get(PROP_WORK_STATUS, 1)
        await self._async_refresh_history(props)
        self.update_interval = timedelta(
            seconds=(
                UPDATE_INTERVAL_IDLE_SECONDS
                if work_status in IDLE_WORK_STATUSES
                else UPDATE_INTERVAL_SECONDS
            )
        )
        shapes = self._map.room_shapes if self._map else []
        tasks = list(self._tasks.values())

        return {
            "online": props.get(PROP_ONLINE, False),
            "battery": props.get(PROP_BATTERY, 0),
            "work_status": work_status,
            "error_code": _first_error_code(props.get(PROP_ERROR_CODE, 0)),
            "clean_mode": props.get(PROP_CLEAN_MODE, {}),
            "clean_summary": props.get(PROP_CLEAN_SUMMARY, {}),
            "firmware": props.get(PROP_FIRMWARE, ""),
            "rooms": self._rooms,
            "room_activity": room_activity(tasks, shapes, self._rooms),
            "last_task": last_task_summary(tasks, shapes, self._rooms),
        }
