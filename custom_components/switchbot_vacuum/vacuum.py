"""Vacuum entity for SwitchBot Vacuum."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CLEAN_TYPES,
    CMD_CLEAN,
    CMD_CONTROL,
    CMD_FIND_ROBOT,
    CMD_GO_CHARGE,
    DEVICE_TYPE_S10,
    DEVICE_TYPE_TO_MODEL,
    DOMAIN,
    FAN_SPEED_ALIASES,
    FAN_SPEED_LIST,
    FAN_SPEEDS,
    K10_FAMILY_DEVICE_TYPES,
    K10_FAN_LEVEL_TO_SPEED,
    K10_FAN_SPEED_ALIASES,
    K10_FAN_SPEED_LIST,
    K10_WORK_STATUS_CHARGING,
    K10_WORK_STATUS_CLEANING,
    K10_WORK_STATUS_CLEANING_2,
    K10_WORK_STATUS_CLEANING_3,
    K10_WORK_STATUS_COLLECTING_DUST,
    K10_WORK_STATUS_DOCKED,
    K10_WORK_STATUS_GO_CHARGE,
    K10_WORK_STATUS_PAUSED,
    K10_WORK_STATUS_STANDBY,
)
from .coordinator import SwitchBotS10Coordinator

# Segment and VacuumEntityFeature.CLEAN_AREA landed in HA 2026.8. On older cores the
# integration still loads, it just never advertises area cleaning.
try:
    from homeassistant.components.vacuum import Segment
except ImportError:
    Segment = None

CLEAN_AREA_FEATURE = getattr(VacuumEntityFeature, "CLEAN_AREA", None)

_LOGGER = logging.getLogger(__name__)

# K10+ native WorkingStatus values -> HA activity
K10_STATUS_TO_ACTIVITY = {
    K10_WORK_STATUS_STANDBY: VacuumActivity.IDLE,            # 0  fallback
    K10_WORK_STATUS_CLEANING: VacuumActivity.CLEANING,       # 1  DefaultClean
    K10_WORK_STATUS_CLEANING_2: VacuumActivity.CLEANING,     # 2  cleaning variant
    K10_WORK_STATUS_CLEANING_3: VacuumActivity.CLEANING,     # 3  cleaning variant
    K10_WORK_STATUS_PAUSED: VacuumActivity.PAUSED,           # 4
    K10_WORK_STATUS_GO_CHARGE: VacuumActivity.RETURNING,     # 5  isGoCharging
    K10_WORK_STATUS_CHARGING: VacuumActivity.DOCKED,         # 6  isCharging
    K10_WORK_STATUS_DOCKED: VacuumActivity.DOCKED,           # 7  isDocking
    K10_WORK_STATUS_COLLECTING_DUST: VacuumActivity.DOCKED,  # 11 isCollectingDust
}

# S10-family native work_status values -> HA activity. Confirmed from the real API plus
# SweeperUtil.getWorkStatusText in the app, which the S10, S20 and S20 Pro all share.
S10_STATUS_TO_ACTIVITY = {
    1: VacuumActivity.IDLE,      # standby
    2: VacuumActivity.DOCKED,    # charging ✓
    3: VacuumActivity.DOCKED,    # charge done
    4: VacuumActivity.CLEANING,  # launching
    5: VacuumActivity.CLEANING,  # wetting mop
    6: VacuumActivity.CLEANING,  # exploring / room mapping
    7: VacuumActivity.RETURNING, # relocating ✓ (brief during return)
    8: VacuumActivity.CLEANING,  # sweeping+mopping
    9: VacuumActivity.CLEANING,  # sweeping ✓
    10: VacuumActivity.CLEANING, # mopping
    11: VacuumActivity.PAUSED,   # paused ✓
    12: VacuumActivity.CLEANING, # escaping trap
    13: VacuumActivity.ERROR,    # fault
    14: VacuumActivity.RETURNING,# backing to mop wash station
    15: VacuumActivity.RETURNING,# backing to charge ✓
    16: VacuumActivity.DOCKED,   # deeply washing mop
    17: VacuumActivity.DOCKED,   # collecting sewage
    18: VacuumActivity.DOCKED,   # filling clean water
    19: VacuumActivity.RETURNING,# collecting dust at base ✓ (before charging)
    20: VacuumActivity.DOCKED,   # drying mop ✓
    21: VacuumActivity.IDLE,     # sleeping
    22: VacuumActivity.IDLE,     # configuring
    23: VacuumActivity.CLEANING, # remote control
    24: VacuumActivity.RETURNING,# backing to base
    25: VacuumActivity.RETURNING,# backing to dock for shutdown
    26: VacuumActivity.RETURNING,# going to water station
    27: VacuumActivity.DOCKED,   # flushing strainer
    29: VacuumActivity.DOCKED,   # adding water
    30: VacuumActivity.DOCKED,   # adding water
    31: VacuumActivity.IDLE,     # firmware upgrading
    32: VacuumActivity.PAUSED,   # paused
    35: VacuumActivity.CLEANING, # scanning / mapping
    36: VacuumActivity.DOCKED,   # charging at water station
    37: VacuumActivity.RETURNING,# going to water station
}

FAN_LEVEL_TO_SPEED = {v: k for k, v in FAN_SPEEDS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up vacuum entity."""
    coordinator: SwitchBotS10Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SwitchBotS10Vacuum(coordinator)])

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        "clean_rooms",
        {
            vol.Required("rooms"): [str],
            vol.Optional("mode", default="sweep_mop"): vol.In(CLEAN_TYPES),
            vol.Optional("fan_level", default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=4)
            ),
            vol.Optional("water_level", default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=3)
            ),
            vol.Optional("times", default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=2)
            ),
            vol.Optional("force_order", default=True): bool,
        },
        "async_clean_rooms",
    )

    platform.async_register_entity_service(
        "set_clean_mode",
        {
            vol.Optional("mode"): vol.In(CLEAN_TYPES),
            vol.Optional("fan_level"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=4)
            ),
            vol.Optional("water_level"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=3)
            ),
            vol.Optional("times"): vol.All(vol.Coerce(int), vol.Range(min=1, max=2)),
        },
        "async_set_clean_mode",
    )

    platform.async_register_entity_service(
        "force_refresh",
        {},
        "async_force_refresh",
    )


class SwitchBotS10Vacuum(CoordinatorEntity[SwitchBotS10Coordinator], StateVacuumEntity):
    """SwitchBot Vacuum vacuum entity."""

    _attr_supported_features = (
        VacuumEntityFeature.STATE
        | VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.LOCATE
    )
    def __init__(self, coordinator: SwitchBotS10Coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_mac}_vacuum"
        self._attr_name = coordinator.device_name or "SwitchBot Vacuum"
        device_type = coordinator.entry.data.get("device_type", DEVICE_TYPE_S10)
        self._is_k10_family = device_type in K10_FAMILY_DEVICE_TYPES
        self._attr_fan_speed_list = (
            K10_FAN_SPEED_LIST if self._is_k10_family else FAN_SPEED_LIST
        )
        if not self._is_k10_family and CLEAN_AREA_FEATURE is not None:
            self._attr_supported_features |= CLEAN_AREA_FEATURE
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_mac)},
            name=coordinator.device_name or "SwitchBot Vacuum",
            manufacturer="SwitchBot",
            model=DEVICE_TYPE_TO_MODEL.get(device_type, device_type),
            sw_version=coordinator.data.get("firmware", ""),
        )

    @property
    def activity(self) -> VacuumActivity | None:
        """Return current activity."""
        status = self.coordinator.data.get("work_status", 0)
        if self._is_k10_family:
            activity = K10_STATUS_TO_ACTIVITY.get(status)
        else:
            activity = S10_STATUS_TO_ACTIVITY.get(status)
        if activity is None:
            _LOGGER.debug("Unknown work_status=%s for %s", status, self.coordinator.device_mac)
        return activity

    @property
    def battery_level(self) -> int | None:
        """Return battery level."""
        return self.coordinator.data.get("battery")

    @property
    def fan_speed(self) -> str | None:
        """Return current fan speed."""
        mode = self.coordinator.data.get("clean_mode", {})
        if self._is_k10_family:
            level = mode.get("fan_level", 0) if isinstance(mode, dict) else 0
            return K10_FAN_LEVEL_TO_SPEED.get(level, "Quiet")
        level = mode.get("fan_level", 1) if isinstance(mode, dict) else 1
        return FAN_LEVEL_TO_SPEED.get(level, "Quiet")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        mode = self.coordinator.data.get("clean_mode", {})
        summary = self.coordinator.data.get("clean_summary", {})
        attrs: dict[str, Any] = {}

        if isinstance(mode, dict):
            attrs["times"] = mode.get("times", 1)
        if not self._is_k10_family and isinstance(mode, dict):
            attrs["water_level"] = mode.get("water_level", 1)
            attrs["clean_type"] = mode.get("type", "sweep_mop")

        if not self._is_k10_family and isinstance(summary, dict):
            attrs["last_clean_area"] = summary.get("clean_area", 0)
            attrs["last_clean_time"] = summary.get("clean_time", 0)

        attrs["work_status"] = self.coordinator.data.get("work_status", 0)
        attrs["rooms"] = self.coordinator.data.get("rooms", {})
        return attrs

    def _optimistic_update(self, work_status: int) -> None:
        """Immediately set expected status optimistically."""
        new_data = dict(self.coordinator.data)
        new_data["work_status"] = work_status
        self.coordinator.async_set_updated_data(new_data)

    async def async_start(self) -> None:
        """Start cleaning."""
        if self._is_k10_family:
            await self.coordinator.async_send_action(
                "StartDefaultClean", {"CleanTimes": 1}
            )
            self._optimistic_update(K10_WORK_STATUS_CLEANING)
        else:
            await self.coordinator.async_send_command(CMD_CLEAN, {
                "0": "clean_all",
                "1": {
                    "force_order": False,
                    "mode": self.coordinator.current_clean_mode(),
                },
            })
            self._optimistic_update(9)  # sweeping

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop cleaning."""
        if self._is_k10_family:
            await self.coordinator.async_send_action("PauseRobot")
            self._optimistic_update(K10_WORK_STATUS_PAUSED)
        else:
            await self.coordinator.async_send_command(CMD_CONTROL, {"0": "stop"})
            self._optimistic_update(11)  # paused

    async def async_pause(self) -> None:
        """Pause cleaning."""
        if self._is_k10_family:
            await self.coordinator.async_send_action("PauseRobot")
            self._optimistic_update(K10_WORK_STATUS_PAUSED)
        else:
            await self.coordinator.async_send_command(CMD_CONTROL, {"0": "pause"})
            self._optimistic_update(11)  # paused

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return to charging base."""
        if self._is_k10_family:
            await self.coordinator.async_send_action("ReturnChargeBase")
            self._optimistic_update(K10_WORK_STATUS_GO_CHARGE)
        else:
            await self.coordinator.async_send_command(CMD_GO_CHARGE, {})
            self._optimistic_update(15)  # backing to charge

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed."""
        if self._is_k10_family:
            await self.coordinator.async_send_info(
                {"SuctionPowLevel": K10_FAN_SPEED_ALIASES.get(fan_speed.lower(), 0)}
            )
            await self.coordinator.async_request_refresh()
            return
        await self.coordinator.async_change_clean_mode(
            fan_level=FAN_SPEED_ALIASES.get(fan_speed.lower(), 1)
        )

    async def async_locate(self, **kwargs: Any) -> None:
        """Make the vacuum announce its position."""
        if self._is_k10_family:
            _LOGGER.warning("locate is only supported on the S10 family")
            return
        await self.coordinator.async_send_command(CMD_FIND_ROBOT, {})

    async def async_set_clean_mode(
        self,
        mode: str | None = None,
        fan_level: int | None = None,
        water_level: int | None = None,
        times: int | None = None,
    ) -> None:
        """Set the sweep/mop type, suction and water level used by subsequent cleans."""
        if self._is_k10_family:
            _LOGGER.warning(
                "set_clean_mode is only supported on the S10 family (S10/S20/S20 Pro)"
            )
            return
        await self.coordinator.async_change_clean_mode(
            type=mode, fan_level=fan_level, water_level=water_level, times=times
        )

    async def async_send_command(
        self, command: str, params: dict[str, Any] | list[Any] | None = None, **kwargs: Any
    ) -> None:
        """Send a raw command."""
        if params and isinstance(params, dict):
            func_id = params.get("function_id", CMD_CLEAN)
            cmd_params = params.get("params", {})
            await self.coordinator.async_send_command(func_id, cmd_params)

    async def async_clean_rooms(
        self,
        rooms: list[str],
        mode: str = "sweep_mop",
        fan_level: int = 1,
        water_level: int = 1,
        times: int = 1,
        force_order: bool = True,
    ) -> None:
        """Clean specific rooms. Accepts room IDs or names."""
        room_map = self.coordinator.data.get("rooms", {})
        name_to_id = {v: k for k, v in room_map.items()}

        resolved = []
        for room in rooms:
            if room.startswith("ROOM_"):
                resolved.append(room)
            elif room in name_to_id:
                resolved.append(name_to_id[room])
            else:
                _LOGGER.warning("Unknown room: %s", room)
                resolved.append(room)

        if self._is_k10_family:
            _LOGGER.warning(
                "K10+ does not support room-specific cleaning via cloud API "
                "(uses local Qihoo SDK in the official app). Starting whole-house clean."
            )
            await self.coordinator.async_send_action("StartDefaultClean", {"CleanTimes": times})
            self._optimistic_update(K10_WORK_STATUS_CLEANING)
        else:
            room_mode = {
                "fan_level": fan_level,
                "times": times,
                "type": mode,
                "water_level": water_level,
            }
            room_list = [
                {"room_id": r, "mode": dict(room_mode)} for r in resolved
            ]
            await self.coordinator.async_send_command(CMD_CLEAN, {
                "0": "clean_rooms",
                "1": {
                    "force_order": force_order,
                    "mode": room_mode,
                    "rooms": room_list,
                },
            })
        await self.coordinator.async_request_refresh()

    async def async_get_segments(self) -> list[Segment]:
        """Return the rooms on the vacuum's map as cleanable segments."""
        await self.async_force_refresh()
        rooms = self.coordinator.data.get("rooms", {})
        return [Segment(id=room_id, name=name) for room_id, name in rooms.items()]

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        """Clean the given map rooms using the currently selected clean mode."""
        mode = self.coordinator.current_clean_mode()
        await self.async_clean_rooms(
            rooms=list(segment_ids),
            mode=mode["type"],
            fan_level=mode["fan_level"],
            water_level=mode["water_level"],
            times=mode["times"],
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data, flagging segment changes before writing state."""
        self._async_check_segments_changed()
        super()._handle_coordinator_update()

    @callback
    def _async_check_segments_changed(self) -> None:
        """Raise a repair when the map's rooms no longer match the mapped areas."""
        if Segment is None or self._is_k10_family or self.registry_entry is None:
            return
        rooms = self.coordinator.data.get("rooms", {})
        last_seen = self.last_seen_segments
        if not rooms or last_seen is None:
            return
        if {segment.id: segment.name for segment in last_seen} != rooms:
            self.async_create_segments_issue()

    async def async_force_refresh(self) -> None:
        """Force refresh status and room data."""
        await self.coordinator.async_refresh_rooms()
        await self.coordinator.async_refresh()
