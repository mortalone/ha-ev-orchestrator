from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _state_map(states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {x.get("entity_id", ""): x for x in states}


def _age_seconds(state: dict[str, Any] | None) -> float | None:
    if not state:
        return None
    stamp = state.get("last_updated") or state.get("last_changed")
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def _item(sm: dict[str, dict[str, Any]], entity_id: str | None) -> dict[str, Any]:
    if not entity_id:
        return {"entity_id": entity_id or None, "state": None, "available": False, "age_seconds": None}
    state = sm.get(entity_id)
    if not state:
        return {"entity_id": entity_id, "state": None, "available": False, "age_seconds": None}
    value = state.get("state")
    return {
        "entity_id": entity_id,
        "state": value,
        "available": value not in ("unknown", "unavailable", None),
        "age_seconds": _age_seconds(state),
        "attributes": state.get("attributes", {}),
    }


CLEVER_DISCOVERY = {
    "departure_time": {
        "domain": "time",
        "names": ["afgangstidspunkt", "departure time"],
        "suffixes": ["afgangstidspunkt", "departure_time"],
    },
    "power_required": {
        "domain": "number",
        "names": ["ønsket energi", "onsket energi", "desired energy", "power required"],
        "suffixes": ["onsket_energi", "power_required"],
    },
    "smart_charging": {
        "domain": "select",
        "names": ["smart opladning", "smart charging"],
        "suffixes": ["smart_opladning", "smart_charging"],
    },
    "status": {
        "domain": "sensor",
        "names": ["status"],
        "suffixes": ["status"],
    },
    "model": {
        "domain": "sensor",
        "names": ["model"],
        "suffixes": ["model"],
    },
    "phase_count": {
        "domain": "sensor",
        "names": ["faseantal", "phase count"],
        "suffixes": ["faseantal", "phase_count"],
    },
    "ampere": {
        "domain": "sensor",
        "names": ["ampere"],
        "suffixes": ["ampere"],
    },
    "last_seen": {
        "domain": "sensor",
        "names": ["sidst set", "last seen"],
        "suffixes": ["sidst_set", "last_seen"],
    },
    "online": {
        "domain": "binary_sensor",
        "names": ["online"],
        "suffixes": ["online"],
    },
    "is_charging": {
        "domain": "binary_sensor",
        "names": ["oplader", "charging"],
        "suffixes": ["oplader", "is_charging"],
    },
}


def _asciiish(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("ø", "o")
        .replace("å", "a")
        .replace("æ", "ae")
    )


def _discover_clever_entities(
    states: list[dict[str, Any]],
    configured: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Resolve Clever entities even when HA generated Danish/device-prefixed entity IDs."""
    sm = _state_map(states)
    resolved: dict[str, dict[str, Any]] = {}
    discovery: dict[str, Any] = {"auto_discovered": [], "configured_found": [], "missing": []}
    used: set[str] = set()

    for key, rule in CLEVER_DISCOVERY.items():
        configured_id = configured.get(key)
        if configured_id and configured_id in sm:
            resolved[key] = _item(sm, configured_id)
            discovery["configured_found"].append({"key": key, "entity_id": configured_id})
            used.add(configured_id)
            continue

        best: tuple[int, str] | None = None
        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(rule["domain"] + ".") or entity_id in used:
                continue

            attrs = state.get("attributes", {}) or {}
            friendly = _asciiish(attrs.get("friendly_name", ""))
            object_id = _asciiish(entity_id.split(".", 1)[1] if "." in entity_id else entity_id)
            score = 0

            for name in rule["names"]:
                n = _asciiish(name)
                if friendly == n:
                    score = max(score, 100)
                elif friendly.endswith(" " + n):
                    score = max(score, 95)
                elif n in friendly:
                    score = max(score, 75)

            for suffix in rule["suffixes"]:
                s = _asciiish(suffix)
                if object_id == s:
                    score = max(score, 92)
                elif object_id.endswith("_" + s):
                    score = max(score, 88)
                elif s in object_id:
                    score = max(score, 65)

            # The Clever integration exposes these entities on one charger device.
            # Requiring a fairly high score avoids accidentally grabbing unrelated
            # generic sensors named "Status", "Model" or "Online".
            threshold = 88 if key in {"status", "model", "online", "ampere"} else 75
            if score >= threshold and (best is None or score > best[0]):
                best = (score, entity_id)

        if best:
            _, entity_id = best
            resolved[key] = _item(sm, entity_id)
            discovery["auto_discovered"].append({"key": key, "entity_id": entity_id})
            used.add(entity_id)
        else:
            resolved[key] = _item(sm, configured_id)
            discovery["missing"].append({"key": key, "configured_entity_id": configured_id})

    discovery["resolved_count"] = sum(1 for item in resolved.values() if item.get("available"))
    discovery["total_count"] = len(CLEVER_DISCOVERY)
    return resolved, discovery


def _vehicle_health(items: dict[str, dict[str, Any]], freshness_key: str = "soc") -> str:
    main = items.get(freshness_key, {})
    if not main.get("available"):
        return "down"
    age = main.get("age_seconds")
    if age is None:
        return "unknown"
    if age > 7200:
        return "stale"
    if age > 1800:
        return "degraded"
    return "ok"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_on(item: dict[str, Any]) -> bool:
    return _norm(item.get("state")) in {"on", "true", "yes", "charging"}


def _fresh(item: dict[str, Any], max_age: int) -> bool:
    if not item.get("available"):
        return False
    age = item.get("age_seconds")
    return age is not None and age <= max_age


def _signal(name: str, item: dict[str, Any], positive_states: list[str], max_age: int) -> dict[str, Any]:
    state = _norm(item.get("state"))
    positive = {_norm(x) for x in positive_states}
    fresh = _fresh(item, max_age)
    if not item.get("entity_id"):
        verdict = "unconfigured"
    elif not item.get("available"):
        verdict = "unknown"
    elif not fresh:
        verdict = "stale"
    elif state in positive:
        verdict = "positive"
    else:
        verdict = "negative"
    return {
        "name": name,
        "entity_id": item.get("entity_id"),
        "state": item.get("state"),
        "age_seconds": item.get("age_seconds"),
        "verdict": verdict,
    }


def _identity_assessment(
    sm: dict[str, dict[str, Any]],
    citroen_items: dict[str, dict[str, Any]],
    mg_items: dict[str, dict[str, Any]],
    shared_items: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    max_age = int(cfg.get("max_signal_age_seconds", 600))
    active = _norm(shared_items.get("active_vehicle", {}).get("state"))

    mg_guard = _item(sm, cfg.get("mg_guard_entity"))
    mg_charging = _item(sm, cfg.get("mg_charging_entity"))
    mg_optional = _item(sm, cfg.get("mg_optional_presence_entity"))
    citroen_beacon = _item(sm, cfg.get("citroen_beacon_entity"))

    mg_signals = [
        _signal("MG kabel/charger connected", mg_guard, cfg.get("mg_guard_present_states", ["on"]), max_age),
        _signal("MG lader", mg_charging, cfg.get("mg_charging_states", ["on", "charging"]), max_age),
    ]
    if cfg.get("mg_optional_presence_entity"):
        mg_signals.append(_signal(
            "MG ekstra presence",
            mg_optional,
            cfg.get("mg_optional_presence_states", ["home", "on", "connected", "present"]),
            max_age,
        ))
    if active:
        mg_signals.append({
            "name": "Aktiv bil helper",
            "entity_id": shared_items.get("active_vehicle", {}).get("entity_id"),
            "state": active,
            "age_seconds": shared_items.get("active_vehicle", {}).get("age_seconds"),
            "verdict": "positive" if active == "mg" else ("negative" if active == "citroen" else "unknown"),
        })

    mg_positive = [x for x in mg_signals if x["verdict"] == "positive"]
    mg_negative = [x for x in mg_signals if x["verdict"] == "negative"]
    mg_unknown = [x for x in mg_signals if x["verdict"] in {"unknown", "stale"}]
    needed = max(1, int(cfg.get("mg_required_negative_signals", 2)))
    unknown_blocks = bool(cfg.get("unknown_blocks_clever", True))
    mg_excluded = not mg_positive and len(mg_negative) >= needed and (not unknown_blocks or not mg_unknown)

    citroen_signals: list[dict[str, Any]] = []
    if cfg.get("citroen_beacon_entity"):
        citroen_signals.append(_signal(
            "Citroën BLE beacon",
            citroen_beacon,
            cfg.get("citroen_beacon_present_states", ["home", "on", "present", "detected"]),
            max_age,
        ))
    connected = citroen_items.get("connected", {})
    if connected.get("entity_id"):
        citroen_signals.append(_signal("Citroën kabel tilsluttet", connected, ["on"], max_age))
    if active:
        citroen_signals.append({
            "name": "Aktiv bil helper",
            "entity_id": shared_items.get("active_vehicle", {}).get("entity_id"),
            "state": active,
            "age_seconds": shared_items.get("active_vehicle", {}).get("age_seconds"),
            "verdict": "positive" if active == "citroen" else ("negative" if active == "mg" else "unknown"),
        })
    citroen_positive = [x for x in citroen_signals if x["verdict"] == "positive"]
    citroen_needed = max(1, int(cfg.get("citroen_required_positive_signals", 1)))
    citroen_identified = len(citroen_positive) >= citroen_needed and not mg_positive

    return {
        "mg_excluded": mg_excluded,
        "mg_positive_count": len(mg_positive),
        "mg_negative_count": len(mg_negative),
        "mg_unknown_count": len(mg_unknown),
        "mg_required_negative_signals": needed,
        "mg_signals": mg_signals,
        "citroen_identified": citroen_identified,
        "citroen_positive_count": len(citroen_positive),
        "citroen_required_positive_signals": citroen_needed,
        "citroen_signals": citroen_signals,
        "active_vehicle": active or None,
        "policy": "fail_closed" if unknown_blocks else "allow_unknown",
    }


def _fallback_assessment(
    citroen_health: str,
    identity: dict[str, Any],
    clever_items: dict[str, dict[str, Any]],
    clever_cfg: dict[str, Any],
) -> dict[str, Any]:
    clever_present = any(x.get("available") for x in clever_items.values())
    clever_online_item = clever_items.get("online", {})
    clever_online = _is_on(clever_online_item) if clever_online_item.get("available") else None
    citroen_degraded = citroen_health in {"degraded", "stale", "down", "unknown"}
    reasons: list[str] = []
    if not identity.get("citroen_identified"):
        reasons.append("Citroën er ikke identificeret med tilstrækkelig sikkerhed")
    if clever_online is False:
        reasons.append("Clever-boksen rapporteres offline")
    if clever_online is None:
        reasons.append("Clever online-status er ukendt")
    if clever_cfg.get("require_mg_excluded", True) and not identity.get("mg_excluded"):
        reasons.append("MG er ikke sikkert udelukket")
    if not citroen_degraded:
        reasons.append("Citroën-telemetri er ikke degraderet")
    eligible = bool(
        clever_cfg.get("enabled", True)
        and clever_cfg.get("use_as_fallback", True)
        and clever_present
        and identity.get("citroen_identified")
        and clever_online is True
        and (identity.get("mg_excluded") or not clever_cfg.get("require_mg_excluded", True))
        and citroen_degraded
    )
    return {
        "eligible": eligible,
        "mg_excluded": bool(identity.get("mg_excluded")),
        "citroen_identified": bool(identity.get("citroen_identified")),
        "clever_present": clever_present,
        "clever_online": clever_online,
        "citroen_degraded": citroen_degraded,
        "strategy": clever_cfg.get("fallback_strategy", "schedule_only"),
        "reasons": reasons,
        "note": "Monitor-only: ingen Clever-kommando sendes i denne version.",
    }


def _stop_verification_status(
    shared_items: dict[str, dict[str, Any]],
    citroen_items: dict[str, dict[str, Any]],
    clever_items: dict[str, dict[str, Any]],
    clever_cfg: dict[str, Any],
) -> dict[str, Any]:
    cfg = clever_cfg.get("soft_stop_zero_kwh", {})
    signals = []
    hp = shared_items.get("house_power", {})
    if hp.get("available"):
        try:
            low = float(hp.get("state")) < float(cfg.get("verify_house_power_below_w", 6000))
        except Exception:
            low = False
        signals.append({"name": "Huseffekt under stop-grænse", "verified": low, "value": hp.get("state")})
    cchg = citroen_items.get("charging", {})
    if cchg.get("available"):
        signals.append({"name": "Citroën charging=off", "verified": not _is_on(cchg), "value": cchg.get("state")})
    live = clever_items.get("is_charging", {})
    if live.get("available"):
        signals.append({"name": "Clever live charging=off", "verified": not _is_on(live), "value": live.get("state")})
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "capability_state": cfg.get("capability_state", "unverified"),
        "automatic": True,
        "signals": signals,
        "verified_now": any(x.get("verified") for x in signals),
        "note": "Verifikation foretages automatisk fra HA/Clever-sensorer; ingen brugerbekræftelse kræves.",
    }


def build_snapshot(states: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    sm = _state_map(states)
    c = settings["citroen"]
    m = settings["mg"]
    shared = settings["shared"]
    identity_cfg = settings.get("identity", {})
    clever_cfg = settings.get("clever", {"entities": {}})

    citroen_items = {k: _item(sm, v) for k, v in c["entities"].items()}
    mg_items = {k: _item(sm, v) for k, v in m["entities"].items()}
    shared_items = {k: _item(sm, v) for k, v in shared.items() if isinstance(v, str) and "." in v}
    clever_items, clever_discovery = _discover_clever_entities(
        states, clever_cfg.get("entities", {})
    )
    citroen_health = _vehicle_health(citroen_items)
    mg_health = _vehicle_health(mg_items)
    identity = _identity_assessment(sm, citroen_items, mg_items, shared_items, identity_cfg)

    clever_status = "available" if any(x.get("available") for x in clever_items.values()) else "not_configured"
    smartcar_status = "not_configured"

    return {
        "mode": settings["mode"],
        "planner": settings["planner"],
        "charger_control": settings.get("charger_control", "vehicle"),
        "citroen": {
            "configured_target_soc": c["target_soc"],
            "configured_minimum_soc": c["minimum_soc"],
            "health": citroen_health,
            "entities": citroen_items,
        },
        "mg": {
            "configured_target_soc": m["target_soc"],
            "configured_minimum_soc": m["minimum_soc"],
            "health": mg_health,
            "entities": mg_items,
        },
        "identity": identity,
        "clever": {
            "health": clever_status,
            "entities": clever_items,
            "discovery": clever_discovery,
            "fallback": _fallback_assessment(citroen_health, identity, clever_items, clever_cfg),
            "soft_stop": _stop_verification_status(shared_items, citroen_items, clever_items, clever_cfg),
            "emulator_required": False,
            "live_session_requires_emulator": True,
        },
        "shared": shared_items,
        "providers": {
            "citroen": [
                {"id": "stellantis_official_b2c", "status": "not_configured", "label": "Stellantis Official B2C"},
                {"id": "smartcar", "status": smartcar_status, "label": "Smartcar"},
                {"id": "psa_car_controller", "status": "not_configured", "label": "PSA Car Controller"},
                {"id": "ha_stellantis_vehicles", "status": citroen_items["soc"]["available"] and "available" or "degraded", "label": "HA Stellantis Vehicles"},
                {"id": "obd_wican", "status": "not_configured", "label": "OBD / WiCAN"},
            ],
            "mg": [
                {"id": "smartcar", "status": smartcar_status, "label": "Smartcar"},
                {"id": "ha_mg", "status": mg_items["soc"]["available"] and "available" or "degraded", "label": "HA MG integration"},
                {"id": "obd_wican", "status": "not_configured", "label": "OBD / WiCAN"},
            ],
            "charger": [
                {"id": "clever_ha", "status": clever_status, "label": "Clever Home Assistant (uden emulator)"}
            ]
        },
    }
