from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


ON_STATES = {"on", "true", "yes", "charging"}
OFF_STATES = {"off", "false", "no", "not_charging", "idle", "disconnected"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _state(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    value = item.get("state")
    if value in (None, "unknown", "unavailable", ""):
        return None
    return _norm(value)


def _bool_state(item: dict[str, Any] | None) -> bool | None:
    value = _state(item)
    if value is None:
        return None
    if value in ON_STATES:
        return True
    if value in OFF_STATES:
        return False
    return None


def _fresh(item: dict[str, Any] | None, max_age: int) -> bool:
    if not item or not item.get("available"):
        return False
    age = item.get("report_age_seconds")
    if age is None:
        age = item.get("age_seconds")
    return age is not None and float(age) <= max_age


def _vehicle_decision(
    name: str,
    vehicle: dict[str, Any],
    active_vehicle: str | None,
    settings: dict[str, Any],
    clever_fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entities = vehicle.get("entities", {})
    planner = _bool_state(entities.get("evsc_charging"))
    charging = _bool_state(entities.get("charging"))
    connected = _bool_state(entities.get("connected"))
    soc_item = entities.get("soc", {})
    max_age = int(settings.get("identity", {}).get("max_signal_age_seconds", 600))
    require_active = bool(settings.get("shadow", {}).get("require_active_vehicle_match", True))

    reasons: list[str] = []
    confidence = "high"
    desired = "unknown"
    action = "observe"
    route = "none"
    alignment = "unknown"

    expected_active = "citroen" if name == "citroen" else "mg"
    if require_active and active_vehicle and active_vehicle not in (expected_active, "unknown", "none"):
        return {
            "vehicle": name,
            "desired": "unknown",
            "action": "blocked_other_vehicle",
            "route": "none",
            "alignment": "not_applicable",
            "confidence": "high",
            "planner": planner,
            "charging": charging,
            "connected": connected,
            "soc": soc_item.get("state"),
            "reasons": [f"Aktiv bil er {active_vehicle}, ikke {expected_active}"],
            "would_execute": False,
        }

    if planner is None:
        reasons.append("EV Smart Charging-planens ON/OFF-state er ukendt")
        confidence = "low"
    else:
        desired = "charge" if planner else "stop"

    if connected is None:
        reasons.append("Tilsluttet-status er ukendt")
        confidence = "low"
    elif not _fresh(entities.get("connected"), max_age):
        reasons.append("Tilsluttet-status er ikke frisk")
        if confidence == "high":
            confidence = "medium"

    if charging is None:
        reasons.append("Ladestatus er ukendt")
        confidence = "low"
    elif not _fresh(entities.get("charging"), max_age):
        reasons.append("Ladestatus er ikke frisk")
        if confidence == "high":
            confidence = "medium"

    if planner is True:
        if connected is False:
            action = "wait_for_connection"
            route = "none"
            reasons.append("Planner ønsker opladning, men bilen rapporteres ikke tilsluttet")
        elif charging is True:
            action = "hold_charging"
            alignment = "aligned"
            route = "vehicle"
        elif charging is False and connected is True:
            action = "would_start"
            alignment = "mismatch"
            route = "mg_vehicle" if name == "mg" else "stellantis"
        else:
            action = "wait_for_fresh_state"
            route = "none"
    elif planner is False:
        if charging is True:
            action = "would_stop"
            alignment = "mismatch"
            route = "mg_vehicle" if name == "mg" else "stellantis"
        elif charging is False:
            action = "hold_stopped"
            alignment = "aligned"
            route = "none"
        else:
            action = "wait_for_fresh_state"
            route = "none"

    if name == "citroen":
        pc = vehicle.get("positive_contact", {})
        if pc.get("available"):
            reasons.append(
                f"Seneste dokumenterede positive bilkontakt: {round(float(pc.get('age_seconds', 0)) / 60, 1)} min siden"
            )
        else:
            reasons.append("Ingen dokumenteret positiv bilkontakt tilgængelig endnu")

        if action in {"would_start", "would_stop"}:
            reasons.append("Shadow-policy: send bilkommando først; explicit wake kun efter dokumenteret command failure")
            fallback = clever_fallback or {}
            if fallback.get("eligible"):
                reasons.append("Clever fallback er aktuelt sikkerhedsmæssigt kvalificeret")
            else:
                block_reasons = fallback.get("reasons") or []
                if block_reasons:
                    reasons.append("Clever fallback blokeret: " + "; ".join(block_reasons[:3]))

    would_execute = action in {"would_start", "would_stop"}

    return {
        "vehicle": name,
        "desired": desired,
        "action": action,
        "route": route,
        "alignment": alignment,
        "confidence": confidence,
        "planner": planner,
        "charging": charging,
        "connected": connected,
        "soc": soc_item.get("state"),
        "reasons": reasons,
        "would_execute": would_execute,
    }


def evaluate_shadow(snapshot: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(settings.get("shadow", {}).get("enabled", True))
    active = _norm(snapshot.get("shared", {}).get("active_vehicle", {}).get("state")) or None
    clever_fallback = snapshot.get("clever", {}).get("fallback", {})

    citroen = _vehicle_decision(
        "citroen",
        snapshot.get("citroen", {}),
        active,
        settings,
        clever_fallback,
    )
    mg = _vehicle_decision(
        "mg",
        snapshot.get("mg", {}),
        active,
        settings,
        None,
    )

    return {
        "enabled": enabled,
        "mode": "shadow",
        "active_vehicle": active,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "citroen": citroen,
        "mg": mg,
        "safety": {
            "sends_commands": False,
            "sends_wake": False,
            "changes_clever": False,
            "changes_automations": False,
        },
    }


def signature(shadow: dict[str, Any]) -> str:
    payload = {
        "active_vehicle": shadow.get("active_vehicle"),
        "citroen": {
            k: shadow.get("citroen", {}).get(k)
            for k in ("desired", "action", "route", "alignment", "confidence", "planner", "charging", "connected")
        },
        "mg": {
            k: shadow.get("mg", {}).get(k)
            for k in ("desired", "action", "route", "alignment", "confidence", "planner", "charging", "connected")
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def coverage_flags(shadow: dict[str, Any], snapshot: dict[str, Any]) -> set[str]:
    flags: set[str] = set()
    for name in ("citroen", "mg"):
        decision = shadow.get(name, {})
        if decision.get("planner") is True:
            flags.add(f"{name}_planner_charge")
        if decision.get("planner") is False:
            flags.add(f"{name}_planner_stop")
        if decision.get("connected") is True:
            flags.add(f"{name}_connected")
        if decision.get("charging") is True:
            flags.add(f"{name}_charging")
        if decision.get("action") == "would_start":
            flags.add(f"{name}_would_start")
        if decision.get("action") == "would_stop":
            flags.add(f"{name}_would_stop")
        if decision.get("alignment") == "mismatch":
            flags.add(f"{name}_mismatch_observed")

    if snapshot.get("citroen", {}).get("positive_contact", {}).get("available"):
        flags.add("citroen_positive_contact")
    if snapshot.get("clever", {}).get("health") == "available":
        flags.add("clever_available")
    if snapshot.get("identity", {}).get("mg_excluded"):
        flags.add("mg_excluded_observed")
    if snapshot.get("identity", {}).get("citroen_identified"):
        flags.add("citroen_identified_observed")
    if snapshot.get("clever", {}).get("fallback", {}).get("eligible"):
        flags.add("clever_fallback_eligible_observed")
    return flags


def update_observations(
    state: dict[str, Any],
    flags: set[str],
    timestamp: str,
) -> dict[str, Any]:
    observations = state.setdefault("observations", {})
    for flag in sorted(flags):
        item = observations.setdefault(flag, {
            "first_seen": timestamp,
            "last_seen": timestamp,
            "samples": 0,
        })
        item["last_seen"] = timestamp
        item["samples"] = int(item.get("samples", 0)) + 1
    return state


def readiness(state: dict[str, Any]) -> dict[str, Any]:
    observations = state.get("observations", {})
    core = [
        "citroen_positive_contact",
        "clever_available",
        "citroen_connected",
        "mg_connected",
        "citroen_planner_charge",
        "citroen_planner_stop",
        "mg_planner_charge",
        "mg_planner_stop",
    ]
    action_coverage = [
        "citroen_would_start",
        "citroen_would_stop",
        "mg_would_start",
        "mg_would_stop",
    ]
    fallback = [
        "mg_excluded_observed",
        "citroen_identified_observed",
        "clever_fallback_eligible_observed",
    ]

    def pack(required: list[str]) -> dict[str, Any]:
        missing = [x for x in required if x not in observations]
        return {
            "ready": not missing,
            "seen": len(required) - len(missing),
            "total": len(required),
            "missing": missing,
        }

    core_result = pack(core)
    action_result = pack(action_coverage)
    fallback_result = pack(fallback)

    return {
        "core": core_result,
        "actions": action_result,
        "fallback_logic": fallback_result,
        "overall_ready_for_review": core_result["ready"] and action_result["ready"],
        "note": "Readiness means enough scenarios have been observed for review; it never enables Control mode automatically.",
    }
