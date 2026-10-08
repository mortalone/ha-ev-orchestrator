DEFAULT_SETTINGS = {
    "mode": "monitor",
    "planner": "ev_smart_charging",
    "charger_control": "vehicle",
    "poll_seconds": 5,
    "audit_seconds": 60,
    "citroen": {
        "target_soc": 85,
        "minimum_soc": 20,
        "low_soc": 20,
        "completion_time": "06:45",
        "max_price": 1.75,
        "auto_wake": True,
        "wake_12v_min": 50,
        "wake_cooldown_minutes": 30,
        "wake_timeout_quarantine_hours": 6,
        "status_check_seconds": [2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 150],
        "entities": {
            "soc": "sensor.citroen_batteri",
            "service_battery": "sensor.vr7bczkxcpe005536_servicebatteri",
            "connected": "binary_sensor.vr7bczkxcpe005536_tilsluttet",
            "charging": "binary_sensor.vr7bczkxcpe005536_oplader",
            "command_status": "sensor.vr7bczkxcpe005536_kommando_status",
            "tracker": "device_tracker.vr7bczkxcpe005536_koretoj",
            "start_button": "button.vr7bczkxcpe005536_start_opladning",
            "stop_button": "button.vr7bczkxcpe005536_stop_opladning",
            "wake_button": "button.vr7bczkxcpe005536_vaekke",
            "target_helper": "input_number.citroen_e_c4_onskede_batteri",
            "evsc_charging": "sensor.ev_smart_charging_charging",
            "evsc_connected": "switch.ev_smart_charging_ev_connected",
            "evsc_minimum_soc": "number.ev_smart_charging_minimum_ev_soc"
        }
    },
    "mg": {
        "target_soc": 90,
        "minimum_soc": 20,
        "low_soc": 20,
        "completion_time": "06:45",
        "max_price": 1.75,
        "entities": {
            "soc": "sensor.lsjwx4098tn028453_soc",
            "connected": "binary_sensor.lsjwx4098tn028453_charger_connected",
            "charging": "binary_sensor.lsjwx4098tn028453_battery_charging",
            "tracker": "device_tracker.lsjwx4098tn028453_vehicle_position",
            "charging_switch": "switch.lsjwx4098tn028453_charging",
            "vehicle_target_soc": "number.lsjwx4098tn028453_target_soc",
            "target_helper": "input_number.mg_s6ev_onskede_batteri",
            "refresh_mode": "select.lsjwx4098tn028453_gateway_refresh_mode",
            "evsc_charging": "sensor.ev_smart_charging_charging_2",
            "evsc_connected": "switch.ev_smart_charging_ev_connected_2",
            "evsc_minimum_soc": "number.ev_smart_charging_minimum_ev_soc_2"
        }
    },
    "shared": {
        "active_vehicle": "input_select.ev_aktiv_bil_ved_lader",
        "house_power": "sensor.house_power_consumption",
        "house_power_live": "sensor.watts_live_effekt",
        "high_power_warning_w": 7000,
        "ev_like_power_w": 9000
    },
    "identity": {
        "max_signal_age_seconds": 600,
        "unknown_blocks_clever": True,
        "mg_required_negative_signals": 2,
        "citroen_required_positive_signals": 1,
        "citroen_beacon_entity": "",
        "citroen_beacon_present_states": ["home", "on", "present", "detected"],
        "mg_guard_entity": "binary_sensor.lsjwx4098tn028453_charger_connected",
        "mg_guard_present_states": ["on", "home", "connected", "charging"],
        "mg_charging_entity": "binary_sensor.lsjwx4098tn028453_battery_charging",
        "mg_charging_states": ["on", "charging"],
        "mg_optional_presence_entity": "",
        "mg_optional_presence_states": ["home", "on", "connected", "present"]
    },
    "clever": {
        "enabled": True,
        "use_as_fallback": True,
        "fallback_strategy": "schedule_only",
        "require_mg_excluded": True,
        "unknown_soc_power_required_kwh": 0,
        "soft_stop_zero_kwh": {
            "enabled": False,
            "learn_automatically": True,
            "verify_timeout_seconds": 120,
            "verify_sustain_seconds": 10,
            "verify_house_power_below_w": 6000,
            "verify_min_power_drop_w": 2500,
            "capability_state": "unverified"
        },
        "entities": {
            "departure_time": "time.departure_time",
            "power_required": "number.power_required",
            "smart_charging": "select.smart_charging",
            "status": "sensor.status",
            "model": "sensor.model",
            "phase_count": "sensor.phase_count",
            "ampere": "sensor.ampere",
            "last_seen": "sensor.last_seen",
            "online": "binary_sensor.online",
            "is_charging": "binary_sensor.is_charging"
        }
    },
    "providers": {
        "citroen_order": [
            "stellantis_official_b2c",
            "smartcar",
            "psa_car_controller",
            "ha_stellantis_vehicles",
            "obd_wican"
        ],
        "mg_order": ["smartcar", "ha_mg", "obd_wican"]
    },
    "shadow": {
        "enabled": True,
        "sample_seconds": 60,
        "history_limit": 2000,
        "require_active_vehicle_match": True,
        "record_unchanged_checkpoint_minutes": 15
    },
    "audit": {
        "enabled": True,
        "show_disabled": True,
        "scan_automations": True,
        "scan_scripts": True
    }
}
