"""Constants for the SwitchBot Vacuum integration."""
from typing import Final

DOMAIN: Final = "switchbot_vacuum"

# Config
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_DEVICE_MAC: Final = "device_mac"
CONF_PRODUCT_KEY: Final = "product_key"
CONF_CACHED_ROOMS: Final = "cached_rooms"

# API
API_AUTH_HOST: Final = "https://account.api.switchbot.net"
CLIENT_ID: Final = "5nnwmhmsa9xxskm14hd85lm9bm"
APP_VERSION: Final = "8.6.1"
API_TIMEOUT: Final = 30
DEVICE_TYPE_S10: Final = "WoSweeperOrigin"
DEVICE_TYPE_S20: Final = "W1106000"
DEVICE_TYPE_S20PRO: Final = "W1107000"
DEVICE_TYPE_K10: Final = "WoSweeperMini"
DEVICE_TYPE_K10PRO: Final = "WoSweeperMiniPro"

# The S20/S20 Pro are protocol-identical to the S10: the app routes all three to the
# same WoSweeperDevice model and "com.switch.bot.sweeper" module, and exposes the same
# shadow properties, function IDs and scene actions for each.
S10_FAMILY_DEVICE_TYPES: Final = frozenset(
    {DEVICE_TYPE_S10, DEVICE_TYPE_S20, DEVICE_TYPE_S20PRO}
)
K10_FAMILY_DEVICE_TYPES: Final = frozenset({DEVICE_TYPE_K10, DEVICE_TYPE_K10PRO})
SUPPORTED_DEVICE_TYPES: Final = S10_FAMILY_DEVICE_TYPES | K10_FAMILY_DEVICE_TYPES

DEVICE_TYPE_TO_MODEL: Final = {
    DEVICE_TYPE_S10: "Floor Cleaning Robot S10",
    DEVICE_TYPE_S20: "Floor Cleaning Robot S20",
    DEVICE_TYPE_S20PRO: "Floor Cleaning Robot S20 Pro",
    DEVICE_TYPE_K10: "Mini Robot Vacuum K10+",
    DEVICE_TYPE_K10PRO: "Mini Robot Vacuum K10+ Pro",
}

# K10+ WorkingStatus values (verified from APK VacuumUtil.smali)
# isCleaning  → [1, 2, 3]
# isPaused    → [4]
# isGoCharging→ [5]
# isCharging  → [6]  (also isDocking)
# isDocking   → [6, 7, 11]
# isCollecting→ [11]
K10_WORK_STATUS_CLEANING: Final = 1
K10_WORK_STATUS_CLEANING_2: Final = 2
K10_WORK_STATUS_CLEANING_3: Final = 3
K10_WORK_STATUS_PAUSED: Final = 4
K10_WORK_STATUS_GO_CHARGE: Final = 5
K10_WORK_STATUS_CHARGING: Final = 6
K10_WORK_STATUS_DOCKED: Final = 7
K10_WORK_STATUS_COLLECTING_DUST: Final = 11
K10_WORK_STATUS_STANDBY: Final = 0  # fallback

# Commands
CMD_CLEAN: Final = 1001
CMD_GO_CHARGE: Final = 1022
CMD_CONTROL: Final = 1009
CMD_CHANGE_MODE: Final = 1043
CMD_FIND_ROBOT: Final = 1019
CMD_SELF_CLEANING: Final = 1039

# Param 0 of CMD_SELF_CLEANING. Only these four values appear in the app; there is no
# stop for dust collection or mop wash.
SELF_CLEAN_MOP_WASH: Final = 1
SELF_CLEAN_START_DRYING: Final = 2
SELF_CLEAN_STOP_DRYING: Final = 3
SELF_CLEAN_DUST_COLLECT: Final = 4

# Work Status (property 1010), per SweeperUtil.getWorkStatusText in the app
WORK_STATUS_STANDBY: Final = 1
WORK_STATUS_CHARGING: Final = 2
WORK_STATUS_CHARGE_DONE: Final = 3
WORK_STATUS_LAUNCHING: Final = 4
WORK_STATUS_WETTING_MOP: Final = 5
WORK_STATUS_RELOCATING: Final = 7
WORK_STATUS_CLEANING: Final = 8
WORK_STATUS_SWEEPING: Final = 9
WORK_STATUS_MOPPING: Final = 10
WORK_STATUS_PAUSED: Final = 11
WORK_STATUS_GO_CHARGE: Final = 15
WORK_STATUS_WASHING_MOP: Final = 16
WORK_STATUS_COLLECTING_SEWAGE: Final = 17
WORK_STATUS_FILLING_WATER: Final = 18
WORK_STATUS_DOCKING: Final = 19
WORK_STATUS_COLLECTING_DUST: Final = 19
WORK_STATUS_DRYING_MOP: Final = 20

# The app greys out the base station buttons while the station is mid-cycle, because
# the commands are rejected then.
STATION_BUSY_STATUSES: Final = frozenset(
    {
        WORK_STATUS_WASHING_MOP,
        WORK_STATUS_COLLECTING_SEWAGE,
        WORK_STATUS_FILLING_WATER,
        WORK_STATUS_COLLECTING_DUST,
    }
)

# Human-readable names for property 1010, mirroring SweeperUtil.getWorkStatusText in
# the app. Shared by the whole S10 family (S10 / S20 / S20 Pro).
WORK_STATUS_NAMES: Final[dict[int, str]] = {
    1: "standby",
    2: "charging",
    3: "charge_done",
    4: "launching",
    5: "wetting_mop",
    6: "exploring",
    7: "relocating",
    8: "sweeping_mopping",
    9: "sweeping",
    10: "mopping",
    11: "paused",
    12: "escaping_trap",
    13: "fault",
    14: "backing_to_wash_mop",
    15: "backing_to_charge",
    16: "deeply_washing_mop",
    17: "collecting_sewage",
    18: "filling_clean_water",
    19: "collecting_dust",
    20: "drying_mop",
    21: "sleeping",
    22: "configuring",
    23: "remote_control",
    24: "backing_to_base",
    25: "backing_to_shut_down",
    26: "going_to_water_station",
    27: "flushing_strainer",
    29: "adding_water",
    30: "adding_water",
    31: "firmware_upgrading",
    32: "paused",
    35: "scanning",
    36: "water_station_charging",
    37: "going_to_water_station",
}

# Properties. IDs verified against the property map in the Sweeper RN bundle; see
# docs/switchbot-vacuum-api.md. 1003 is power and 1019 is upgradeStatus — both were
# previously used here by mistake, which left the error sensor reading the wrong value.
PROP_ONLINE: Final = 66
PROP_BATTERY: Final = 1004
PROP_WORK_STATUS: Final = 1010
PROP_ERROR_CODE: Final = 1011
PROP_TASK_TYPE: Final = 1013
PROP_LAST_TASK_ID: Final = 1015
PROP_MAP_ID: Final = 1023
PROP_S3_BUCKET: Final = 1028
PROP_S3_OBJECT: Final = 1029
PROP_AWS_REGION: Final = 1031
PROP_TASK_INFO: Final = 1032
PROP_ROOM_PLANS: Final = 1038
PROP_MAP_INFO: Final = 1055
PROP_CLEAN_MODE: Final = 1053
PROP_CLEAN_SUMMARY: Final = 1052
PROP_AWS_CREDS: Final = 1130
PROP_FIRMWARE: Final = 1002

K10PRO_PROP_ONLINE: Final = 66
K10PRO_PROP_BATTERY: Final = 820
K10PRO_PROP_SUCTION_POW_LEVEL: Final = 4601
K10PRO_PROP_WORK_STATUS: Final = 4602
K10PRO_PROP_DUST_COLECT_FREQUENCY: Final = 4609
K10PRO_PROP_CHILD_LOCK: Final = 4610
K10PRO_PROP_DUST_COLECT_TIME: Final = 4614
K10PRO_PROP_AUTO_RESTART: Final = 4615

# Fan speed mapping (S10). HA renders these strings verbatim in the UI, so they are
# capitalized; the lowercase aliases below keep pre-0.7 automations working.
FAN_SPEEDS: Final = {
    "Quiet": 1,
    "Standard": 2,
    "Strong": 3,
    "Max": 4,
}
FAN_SPEED_LIST: Final = list(FAN_SPEEDS.keys())

# Fan speed mapping (K10+) — SuctionPowLevel 0-3 (confirmed via app: quiet/standard/strong/max)
K10_FAN_SPEEDS: Final = {
    "Quiet": 0,
    "Standard": 1,
    "Strong": 2,
    "Max": 3,
}
K10_FAN_SPEED_LIST: Final = list(K10_FAN_SPEEDS.keys())
K10_FAN_LEVEL_TO_SPEED: Final = {v: k for k, v in K10_FAN_SPEEDS.items()}

FAN_SPEED_ALIASES: Final = {name.lower(): level for name, level in FAN_SPEEDS.items()}
K10_FAN_SPEED_ALIASES: Final = {
    name.lower(): level for name, level in K10_FAN_SPEEDS.items()
}

# Clean types accepted in the "type" field of property 1053 / function 1043
CLEAN_TYPE_SWEEP: Final = "sweep"
CLEAN_TYPE_MOP: Final = "mop"
CLEAN_TYPE_SWEEP_MOP: Final = "sweep_mop"
CLEAN_TYPE_SWEEP_THEN_MOP: Final = "first_sweep_then_mop"
CLEAN_TYPES: Final = [
    CLEAN_TYPE_SWEEP,
    CLEAN_TYPE_MOP,
    CLEAN_TYPE_SWEEP_MOP,
    CLEAN_TYPE_SWEEP_THEN_MOP,
]

# Water output levels for the "water_level" field of property 1053 / function 1043
WATER_LEVELS: Final = {"low": 1, "medium": 2, "high": 3}
WATER_LEVEL_LIST: Final = list(WATER_LEVELS.keys())
WATER_LEVEL_TO_NAME: Final = {v: k for k, v in WATER_LEVELS.items()}

# Cleaning passes for the "times" field
CLEAN_PASSES: Final = {"1": 1, "2": 2}
CLEAN_PASS_LIST: Final = list(CLEAN_PASSES.keys())

# Work status indicating fault (S10)
WORK_STATUS_FAULT: Final = 13

# Error codes (property 1011), transcribed from the ErrorCode enum in the Sweeper RN
# bundle. See docs/switchbot-vacuum-api.md. The previous table mapped 2000-2012 to
# Qihoo 360 SDK meanings, which belong to a different device family entirely.
ERROR_CODES: Final[dict[int, str]] = {
    0: "none",
    # 1xxx — robot hardware
    1001: "fan_exception",
    1002: "unknown_hardware_failure",
    1003: "battery_exception",
    # 2xxx — robot faults
    2001: "water_station_leak",
    2002: "cliff_sensor_anomaly",
    2003: "device_vacant",
    2004: "roller_lock",
    2005: "wheel_lock",
    2006: "lcd_lock",
    2007: "side_brush_lock",
    2008: "dust_box_not_installed",
    2009: "device_stuck",
    2010: "device_tilted",
    2011: "bumper_strip_lock",
    2012: "radar_locked",
    2013: "radar_covered",
    2014: "chargeback_sensor_anomaly",
    2015: "carpet_detection_sensor_anomaly",
    2016: "obstacle_avoidance_sensor_anomaly",
    2017: "wall_sensor_anomaly",
    2018: "cannot_find_dust_station",
    2019: "dust_station_blocked",
    2020: "host_in_forbidden_area",
    2022: "cannot_find_water_station",
    2024: "systems_error",
    2025: "roller_up_down_lock",
    2026: "water_station_communication_failure",
    2027: "dust_station_communication_failure",
    2028: "connect_failed",
    2030: "pose_lost",
    2031: "cannot_start_in_carpeted_area",
    2032: "no_map_charge",
    2033: "cannot_find_humidifier",
    2034: "docking_station_fail",
    2035: "docking_station_fail",
    2036: "docking_station_fail",
    2037: "no_open",
    2038: "combined_base_error",
    2039: "combined_base_error",
    2046: "base_version_low",
    2047: "location_fail_map_not_full",
    2048: "current_map_not_change_base",
    # 3xxx — base station and consumables
    3002: "area_cannot_be_reached",
    3003: "filling_water_exception",
    3004: "sewage_exception",
    3005: "roller_missing",
    3006: "slop_box_missing",
    3007: "slop_tank_missing",
    3008: "dust_bag_not_installed",
    3009: "dust_cover_open",
    3010: "dust_bag_full",
    3011: "install_external_sewage_slop_tank",
    3012: "install_external_sewage_purging_tank",
    3013: "sewage_slop_tank_full",
    3014: "sewage_purging_tank_shortage",
    3015: "high_drying_temperature",
    3016: "camera_exception",
    3017: "host_blocked",
    3018: "unable_to_water_station",
    3019: "unable_to_dust_station",
    3020: "unable_to_humidifier_station",
    3021: "clean_water_pump_cannot_work",
    3062: "water_base_error",
    # 4xxx — power and scheduling
    4001: "clean_water_tank_shortage",
    4002: "low_power_shut_down",
    4004: "low_power",
    4005: "charge_exception",
    4006: "dust_station_pair_failed",
    4007: "dust_station_bind_failed",
    4008: "water_station_pair_failed",
    4009: "water_station_bind_failed",
    4010: "water_station_low_power",
    4011: "task_skipped_do_not_disturb",
    4012: "task_skipped_low_power",
    4013: "task_skipped_reserved",
    4014: "combined_base_error",
    4015: "task_skipped_reserved",
    4018: "combined_base_error",
    4019: "combined_base_error",
    4020: "combined_base_error",
    4021: "combined_base_error",
    4028: "water_base_error",
    4029: "sweeper_low_power",
}
ERROR_CODES.update(
    {code: "water_station_communication_error" for code in range(3022, 3032)}
)
ERROR_CODES.update(
    {code: "dust_station_communication_error" for code in range(3032, 3039)}
)
ERROR_CODES.update(
    {code: "humidifier_communication_error" for code in range(3039, 3041)}
)
ERROR_CODES.update({code: "combined_base_error" for code in range(3041, 3062)})

# Codes reporting a skipped task rather than a fault, so they must not light up the
# problem binary sensor.
NON_ERROR_STATUS_CODES: Final = frozenset({0, 4011, 4012, 4013, 4015})

# Separate operational failure reasons (from APK operateFail* strings)
# These appear as transient conditions checked before/during commands.
OPERATIONAL_ERRORS: Final[dict[str, str]] = {
    "operateFailLowBattery": "Low battery",
    "operateFailClearWaterEmpty": "Clean water tank empty",
    "operateFailDirtWaterFull": "Dirty water tank full",
    "operateFailNoClearWater": "No clean water tank",
    "operateFailNoDirtWater": "No dirty water tank",
    "operateFailOutBaseStation": "Robot not at base station",
    "operateFailOutStation": "Robot not at station",
    "operateFailRepeatControl": "Duplicate command",
}

# S3
S3_REGION: Final = "eu-central-1"
DEFAULT_S3_BUCKET: Final = "prod-eu-sweeper-origin"

# Timings
UPDATE_INTERVAL_SECONDS: Final = 30
# Polling is relaxed while the robot only sits in its station.
UPDATE_INTERVAL_IDLE_SECONDS: Final = 300
IDLE_WORK_STATUSES: Final = frozenset({1, 2, 3, 16, 17, 18, 19, 20, 21, 27, 29, 30, 36})
# Task records are fetched when a task starts or ends, plus a rare safety refresh.
HISTORY_FOLLOWUP_SECONDS: Final = 120
HISTORY_FOLLOWUP_WINDOW_SECONDS: Final = 600
HISTORY_SAFETY_REFRESH_SECONDS: Final = 21600
TOKEN_REFRESH_SECONDS: Final = 5400  # 1.5 hours
ROOM_REFRESH_SECONDS: Final = 86400  # 24 hours
# The map is downloaded when its metadata changes, plus a daily safety refresh.
MAP_MIN_REFRESH_SECONDS: Final = 600
MAP_RETRY_SECONDS: Final = 3600
MAP_SAFETY_REFRESH_SECONDS: Final = 86400
