"""Sensor entities for SwitchBot Vacuum rooms."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ERROR_CODES,
    K10_FAMILY_DEVICE_TYPES,
    WORK_STATUS_FAULT,
    WORK_STATUS_NAMES,
)
from .coordinator import SwitchBotS10Coordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanSummaryDescription(SensorEntityDescription):
    """Description for clean summary sensor."""
    summary_key: str = ""
    scale: float = 1.0


CLEAN_SUMMARY_SENSORS: list[CleanSummaryDescription] = [
    CleanSummaryDescription(
        key="clean_area",
        summary_key="clean_area",
        name="Clean Area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:floor-plan",
        scale=1.0,
    ),
    CleanSummaryDescription(
        key="total_area",
        summary_key="total_area",
        name="Total Area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:floor-plan",
        scale=1.0,
    ),
    CleanSummaryDescription(
        key="clean_time",
        summary_key="clean_time_ms",
        name="Clean Time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.001,
    ),
    CleanSummaryDescription(
        key="duration",
        summary_key="duration",
        name="Session Duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.001,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up room sensor entities."""
    coordinator: SwitchBotS10Coordinator = hass.data[DOMAIN][entry.entry_id]
    device_type = entry.data.get("device_type", "")

    entities: list[SensorEntity] = [SwitchBotVacuumError(coordinator)]

    if device_type not in K10_FAMILY_DEVICE_TYPES:
        entities.append(SwitchBotVacuumStatus(coordinator))
        entities.append(SwitchBotLastCleanSensor(coordinator))
        entities.extend(
            SwitchBotCleanSummarySensor(coordinator, desc)
            for desc in CLEAN_SUMMARY_SENSORS
        )

    async_add_entities(entities)

    known_room_ids: set[str] = set()

    @callback
    def _async_add_new_rooms() -> None:
        """Add sensor entities for newly discovered rooms."""
        rooms = coordinator.data.get("rooms", {})
        new_entities = []
        for room_id, room_name in rooms.items():
            if room_id not in known_room_ids:
                known_room_ids.add(room_id)
                new_entities.append(
                    SwitchBotRoomSensor(coordinator, room_id, room_name)
                )
                if device_type not in K10_FAMILY_DEVICE_TYPES:
                    new_entities.extend(
                        SwitchBotRoomActivitySensor(coordinator, room_id, room_name, kind)
                        for kind in ROOM_ACTIVITY_KINDS
                    )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_new_rooms()
    coordinator.async_add_listener(_async_add_new_rooms)


ROOM_ACTIVITY_KINDS: dict[str, str] = {"vacuumed": "Vacuumed", "mopped": "Mopped"}


def _room_object_id(room_id: str) -> str:
    """Build an entity ID from the room ID, which stays stable when a room is renamed."""
    return f"switchbot_vacuum_{room_id.lower()}"


def _from_ms(value: int | None) -> datetime | None:
    """Convert a cloud timestamp in milliseconds to a datetime."""
    return datetime.fromtimestamp(value / 1000, tz=UTC) if value else None


class SwitchBotLastCleanSensor(CoordinatorEntity[SwitchBotS10Coordinator], SensorEntity):
    """When the last real cleaning run ended, with its rooms and mode as attributes."""

    _attr_name = "Last Clean"
    _attr_icon = "mdi:broom"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SwitchBotS10Coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_mac}_last_clean"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_mac)},
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the end of the last run."""
        last = self.coordinator.data.get("last_task")
        return _from_ms(last["end_ms"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return what the last run did."""
        last = self.coordinator.data.get("last_task")
        if not last:
            return {}
        return {
            "start": _from_ms(last["start_ms"]).isoformat(),
            "rooms": last["rooms"],
            "room_ids": last["room_ids"],
            "vacuumed": last["vacuumed"],
            "mopped": last["mopped"],
            "clean_minutes": last["clean_minutes"],
            "area": last["area"],
            "action": last["action"],
            "result": last["result"],
            "source": last["source"],
        }


class SwitchBotRoomActivitySensor(CoordinatorEntity[SwitchBotS10Coordinator], SensorEntity):
    """When a room was last vacuumed or mopped."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-check"

    def __init__(
        self,
        coordinator: SwitchBotS10Coordinator,
        room_id: str,
        room_name: str,
        kind: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._room_id = room_id
        self._kind = kind
        self._attr_unique_id = f"{coordinator.device_mac}_room_{room_id}_{kind}"
        self.entity_id = f"sensor.{_room_object_id(room_id)}_{kind}"
        self._attr_name = f"{room_name} {ROOM_ACTIVITY_KINDS[kind]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_mac)},
        )

    @property
    def native_value(self) -> datetime | None:
        """Return when the room was last cleaned this way."""
        activity = self.coordinator.data.get("room_activity", {})
        return _from_ms(activity.get(self._room_id, {}).get(self._kind))

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the room ID."""
        return {"room_id": self._room_id}


class SwitchBotRoomSensor(CoordinatorEntity[SwitchBotS10Coordinator], SensorEntity):
    """Sensor representing a room known to the vacuum."""

    def __init__(
        self,
        coordinator: SwitchBotS10Coordinator,
        room_id: str,
        room_name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._room_id = room_id
        self._attr_unique_id = f"{coordinator.device_mac}_room_{room_id}"
        self.entity_id = f"sensor.{_room_object_id(room_id)}"
        self._attr_name = room_name
        self._attr_icon = "mdi:floor-plan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_mac)},
        )

    @property
    def native_value(self) -> str:
        """Return room name (updates if renamed in app)."""
        rooms = self.coordinator.data.get("rooms", {})
        return rooms.get(self._room_id, self._room_id)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return room ID as attribute."""
        return {"room_id": self._room_id}


class SwitchBotCleanSummarySensor(CoordinatorEntity[SwitchBotS10Coordinator], SensorEntity):
    """Sensor for S10 clean summary metrics."""

    entity_description: CleanSummaryDescription

    def __init__(
        self,
        coordinator: SwitchBotS10Coordinator,
        description: CleanSummaryDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_mac}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_mac)},
        )

    @property
    def native_value(self) -> float | None:
        """Return the sensor value."""
        summary = self.coordinator.data.get("clean_summary", {})
        if not isinstance(summary, dict):
            return None
        raw = summary.get(self.entity_description.summary_key)
        if raw is None:
            return None
        return round(raw * self.entity_description.scale, 1)


class SwitchBotVacuumStatus(CoordinatorEntity[SwitchBotS10Coordinator], SensorEntity):
    """Sensor exposing the raw work status name, for finer automation triggers.

    The vacuum entity collapses every base station activity into DOCKED; this keeps the
    distinction between drying, washing, dust collection and refilling.
    """

    _attr_name = "Status"
    _attr_icon = "mdi:robot-vacuum"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = sorted(set(WORK_STATUS_NAMES.values()) | {"unknown"})

    def __init__(self, coordinator: SwitchBotS10Coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_mac}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_mac)},
        )

    @property
    def native_value(self) -> str:
        """Return the work status name."""
        status = self.coordinator.data.get("work_status", 0)
        name = WORK_STATUS_NAMES.get(status)
        if name is None:
            _LOGGER.debug("Unknown SwitchBot vacuum work_status %s", status)
            return "unknown"
        return name

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        """Return the raw status code."""
        return {"work_status": self.coordinator.data.get("work_status", 0)}


class SwitchBotVacuumError(CoordinatorEntity[SwitchBotS10Coordinator], SensorEntity):
    """Sensor showing current error type as state for automations."""

    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: SwitchBotS10Coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_mac}_error"
        self._attr_name = "Error"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_mac)},
        )

    @property
    def native_value(self) -> str:
        """Return error type string for automation triggers."""
        error_code = self.coordinator.data.get("error_code", 0)
        work_status = self.coordinator.data.get("work_status", 0)
        if error_code == 0 and work_status == WORK_STATUS_FAULT:
            return "fault"
        return _resolve_error(error_code)

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        """Return raw error code for advanced automations."""
        error_code = self.coordinator.data.get("error_code", 0)
        return {
            "error_code": error_code,
            "error_description": ERROR_CODES.get(
                error_code, f"Unknown error {error_code}"
            ),
            "work_status": self.coordinator.data.get("work_status", 0),
        }


def _resolve_error(error_code: int) -> str:
    """Map error code to string, logging unknown codes."""
    if error_code in ERROR_CODES:
        return ERROR_CODES[error_code]
    _LOGGER.warning(
        "Unknown SwitchBot vacuum error code %d — please report this",
        error_code,
    )
    return f"error_{error_code}"
