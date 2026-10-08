from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _state_map(states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {x.get("entity_id", ""): x for x in states}


def _age_seconds(state: dict[str, Any] | None) -> float | None:
    """Age of the last value/attribute change recorded by Home Assistant."""
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


def _reported_age_seconds(state: dict[str, Any] | None) -> float | None:
    """Age of the last report from the integration, even if the value did not change."""
    if not state:
        return None
    stamp = state.get("last_reported") or state.get("last_updated") or state.get("last_changed")
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
        "report_age_seconds": _reported_age_seconds(state),
        "last_updated": state.get("last_updated"),
        "last_changed": state.get("last_changed"),
        "last_reported": state.get("last_reported"),
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


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, "", "unknown", "unavailable"):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _provider_positive_contact(items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Best evidence that data/command actually reached the vehicle/provider.

    This deliberately does NOT treat ordinary HA last_updated as vehicle contact.
    Preferred evidence is a vehicle/provider timestamp exposed inside entity
    attributes, or a completed remote command.
    """
    now = datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []
    timestamp_keys = {
        "last_updated", "updated_at", "last_update", "last_seen",
        "sidst_opdateret", "senest_opdateret", "sidst_set",
    }

    for key, item in items.items():
        attrs = item.get("attributes") or {}
        for attr_key, attr_value in attrs.items():
            norm_key = _asciiish(attr_key).replace(" ", "_").replace("-", "_")
            if norm_key not in {_asciiish(x).replace(" ", "_") for x in timestamp_keys}:
                continue
            dt = _parse_dt(attr_value)
            if not dt:
                continue
            # Ignore obviously bad future timestamps.
            if (dt - now).total_seconds() > 300:
                continue
            candidates.append({
                "timestamp": dt,
                "source": item.get("entity_id"),
                "evidence": f"provider timestamp: {attr_key}",
                "confidence": "medium",
            })

    command = items.get("command_status", {})
    command_state = _asciiish(command.get("state"))
    success_tokens = ("udfort", "udført", "done", "success", "successful", "completed")
    if any(token in command_state for token in success_tokens) or command_state == "0":
        dt = _parse_dt(command.get("last_updated"))
        if dt:
            candidates.append({
                "timestamp": dt,
                "source": command.get("entity_id"),
                "evidence": "remote command completed",
                "confidence": "high",
            })

    if not candidates:
        return {
            "available": False,
            "timestamp": None,
            "age_seconds": None,
            "source": None,
            "evidence": None,
            "confidence": None,
        }

    best = max(candidates, key=lambda x: x["timestamp"])
    return {
        "available": True,
        "timestamp": best["timestamp"].isoformat(),
        "age_seconds": max(0.0, (now - best["timestamp"]).total_seconds()),
        "source": best["source"],
        "evidence": best["evidence"],
        "confidence": best["confidence"],
    }


def _command_contact_expectation(items: dict[str, dict[str, Any]], timeout_seconds: int = 180) -> dict[str, Any]:
    command = items.get("command_status", {})
    if not command.get("available"):
        return {"state": "none", "expected": False, "age_seconds": None, "status": None}

    raw = str(command.get("state") or "")
    state = _asciiish(raw)
    age = command.get("age_seconds")
    pending_tokens = (
        "accepteret", "accepted", "vaekker", "vækker", "waking",
        "videresendt", "forwarded", "checking", "in progress", "igang",
    )
    success_tokens = ("udfort", "udført", "done", "success", "successful", "completed")
    failure_tokens = ("tidsudlob", "tidsudløb", "timeout", "fejl", "failed", "error")

    if any(token in state for token in pending_tokens):
        overdue = age is not None and float(age) > timeout_seconds
        return {
            "state": "overdue" if overdue else "waiting",
            "expected": True,
            "age_seconds": age,
            "timeout_seconds": timeout_seconds,
            "status": raw,
        }
    if any(token in state for token in failure_tokens):
        return {"state": "failed", "expected": False, "age_seconds": age, "status": raw}
    if any(token in state for token in success_tokens) or state == "0":
        return {"state": "success", "expected": False, "age_seconds": age, "status": raw}
    return {"state": "idle", "expected": False, "age_seconds": age, "status": raw}


def _object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1] if "." in entity_id else entity_id


def _derive_prefix(entity_id: str, suffixes: list[str]) -> str | None:
    obj = _asciiish(_object_id(entity_id))
    for suffix in suffixes:
        s = _asciiish(suffix)
        if obj == s:
            return ""
        marker = "_" + s
        if obj.endswith(marker):
            return obj[: -len(marker)]
    return None


def _discover_clever_entities(
    states: list[dict[str, Any]],
    configured: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Resolve Clever entities while avoiding unrelated generic HA entities.

    Clever's entity IDs normally share a charger/device prefix. We first resolve
    strong, distinctive entities and derive that prefix. Generic names such as
    Status, Online and Charging are only accepted when they share the same prefix.
    """
    sm = _state_map(states)
    resolved: dict[str, dict[str, Any]] = {}
    discovery: dict[str, Any] = {
        "auto_discovered": [],
        "configured_found": [],
        "missing": [],
        "charger_prefix": None,
    }
    used: set[str] = set()

    strong_keys = [
        "departure_time",
        "power_required",
        "smart_charging",
        "model",
        "phase_count",
        "ampere",
        "last_seen",
    ]
    generic_keys = ["status", "online", "is_charging"]

    def best_match(key: str, required_prefix: str | None = None) -> str | None:
        rule = CLEVER_DISCOVERY[key]
        best: tuple[int, str] | None = None
        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(rule["domain"] + ".") or entity_id in used:
                continue
            obj = _asciiish(_object_id(entity_id))
            if required_prefix is not None:
                if required_prefix == "":
                    pass
                elif not (obj == required_prefix or obj.startswith(required_prefix + "_")):
                    continue

            attrs = state.get("attributes", {}) or {}
            friendly = _asciiish(attrs.get("friendly_name", ""))
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
                if obj == s:
                    score = max(score, 92)
                elif obj.endswith("_" + s):
                    score = max(score, 88)
                elif s in obj:
                    score = max(score, 65)

            threshold = 75 if key in strong_keys else 88
            if score >= threshold and (best is None or score > best[0]):
                best = (score, entity_id)
        return best[1] if best else None

    # Honor configured IDs when they exist.
    for key in CLEVER_DISCOVERY:
        configured_id = configured.get(key)
        if configured_id and configured_id in sm:
            resolved[key] = _item(sm, configured_id)
            discovery["configured_found"].append({"key": key, "entity_id": configured_id})
            used.add(configured_id)

    # First pass: distinctive charger entities.
    for key in strong_keys:
        if key in resolved:
            continue
        entity_id = best_match(key)
        if entity_id:
            resolved[key] = _item(sm, entity_id)
            discovery["auto_discovered"].append({"key": key, "entity_id": entity_id})
            used.add(entity_id)

    # Derive the common charger prefix from the strongest resolved controls.
    prefixes: list[str] = []
    for key in ("power_required", "departure_time", "smart_charging", "model"):
        item = resolved.get(key)
        if not item or not item.get("entity_id"):
            continue
        prefix = _derive_prefix(item["entity_id"], CLEVER_DISCOVERY[key]["suffixes"])
        if prefix is not None:
            prefixes.append(prefix)

    charger_prefix: str | None = None
    if prefixes:
        # Prefer the longest prefix; it is normally the full charger/device slug.
        charger_prefix = sorted(prefixes, key=len, reverse=True)[0]
        discovery["charger_prefix"] = charger_prefix

    # Second pass: generic fields MUST be on the same charger prefix.
    for key in generic_keys:
        if key in resolved:
            continue
        entity_id = best_match(key, required_prefix=charger_prefix) if charger_prefix is not None else None
        if entity_id:
            resolved[key] = _item(sm, entity_id)
            discovery["auto_discovered"].append({"key": key, "entity_id": entity_id})
            used.add(entity_id)

    for key in CLEVER_DISCOVERY:
        if key not in resolved:
            configured_id = configured.get(key)
            resolved[key] = _item(sm, configured_id)
            discovery["missing"].append({"key": key, "configured_entity_id": configured_id})

    discovery["resolved_count"] = sum(1 for item in resolved.values() if item.get("available"))
    discovery["total_count"] = len(CLEVER_DISCOVERY)
    return resolved, discovery

def _vehicle_health(items: dict[str, dict[str, Any]], freshness_key: str = "soc") -> str:
    """Telemetry freshness, based on last_reported when Home Assistant provides it.

    A stationary vehicle can keep the same SOC for hours. That must not be
    confused with an integration which has stopped reporting.
    """
    main = items.get(freshness_key, {})
    if not main.get("available"):
        return "down"
    age = main.get("report_age_seconds")
    if age is None:
        return "unknown"
    if age > 7200:
        return "stale"
    if age > 1800:
        return "degraded"
    return "ok"


def _contact_summary(items: dict[str, dict[str, Any]], keys: list[str]) -> dict[str, Any]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for key in keys:
        item = items.get(key, {})
        age = item.get("age_seconds")
        if item.get("available") and age is not None:
            candidates.append((float(age), item))
    if not candidates:
        return {
            "age_seconds": None,
            "entity_id": None,
            "timestamp": None,
            "state": None,
        }
    age, item = min(candidates, key=lambda x: x[0])
    timestamp = None
    try:
        timestamp = (datetime.now(timezone.utc) - __import__("datetime").timedelta(seconds=age)).isoformat()
    except Exception:
        pass
    return {
        "age_seconds": age,
        "entity_id": item.get("entity_id"),
        "timestamp": timestamp,
        "state": item.get("state"),
    }


def _timestamp_state_age(item: dict[str, Any]) -> float | None:
    value = item.get("state")
    if not value or value in ("unknown", "unavailable"):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None

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
    citroen_contact = _contact_summary(
        citroen_items, ["soc", "service_battery", "connected", "charging", "command_status", "tracker"]
    )
    mg_contact = _contact_summary(
        mg_items, ["soc", "connected", "charging", "tracker", "vehicle_target_soc"]
    )
    citroen_positive_contact = _provider_positive_contact(citroen_items)
    mg_positive_contact = _provider_positive_contact(mg_items)
    citroen_contact_expectation = _command_contact_expectation(citroen_items, 180)
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
            "last_contact": citroen_contact,
            "positive_contact": citroen_positive_contact,
            "contact_expectation": citroen_contact_expectation,
            "entities": citroen_items,
        },
        "mg": {
            "configured_target_soc": m["target_soc"],
            "configured_minimum_soc": m["minimum_soc"],
            "health": mg_health,
            "last_contact": mg_contact,
            "positive_contact": mg_positive_contact,
            "contact_expectation": {"state": "none", "expected": False},
            "entities": mg_items,
        },
        "identity": identity,
        "clever": {
            "health": clever_status,
            "entities": clever_items,
            "discovery": clever_discovery,
            "last_seen_age_seconds": _timestamp_state_age(clever_items.get("last_seen", {})),
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
