from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import yaml


HOMEASSISTANT_DIR = Path("/homeassistant")
AUTOMATIONS = HOMEASSISTANT_DIR / "automations.yaml"
SCRIPTS = HOMEASSISTANT_DIR / "scripts.yaml"

CITROEN_WAKE = "button.vr7bczkxcpe005536_vaekke"
CITROEN_START = "button.vr7bczkxcpe005536_start_opladning"
CITROEN_STOP = "button.vr7bczkxcpe005536_stop_opladning"
MG_SWITCH = "switch.lsjwx4098tn028453_charging"
CITROEN_MIN = "number.ev_smart_charging_minimum_ev_soc"
MG_MIN = "number.ev_smart_charging_minimum_ev_soc_2"


class LenientLoader(yaml.SafeLoader):
    pass


def _unknown(loader: LenientLoader, tag_suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


LenientLoader.add_multi_constructor("!", _unknown)


@dataclass
class Finding:
    code: str
    severity: str
    kind: str
    name: str
    yaml_id: str | None
    entity_id: str | None
    enabled: bool | None
    runtime_state: str | None
    file: str
    line: int | None
    reason: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dump_text(value: Any) -> str:
    try:
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    except Exception:
        return str(value)


def _line_for(raw: str, needle: str) -> int | None:
    if not needle:
        return None
    for idx, line in enumerate(raw.splitlines(), 1):
        if needle in line:
            return idx
    return None


def _automation_entity(yaml_id: str | None, name: str, ha_states: list[dict[str, Any]]) -> tuple[str | None, bool | None, str | None]:
    for state in ha_states:
        eid = state.get("entity_id", "")
        if not eid.startswith("automation."):
            continue
        attrs = state.get("attributes", {})
        if yaml_id and str(attrs.get("id", "")) == str(yaml_id):
            return eid, state.get("state") == "on", state.get("state")
    for state in ha_states:
        eid = state.get("entity_id", "")
        if not eid.startswith("automation."):
            continue
        if state.get("attributes", {}).get("friendly_name") == name:
            return eid, state.get("state") == "on", state.get("state")
    return None, None, None


def _script_entity(key: str, ha_states: list[dict[str, Any]]) -> tuple[str | None, bool | None, str | None]:
    entity_id = f"script.{key}"
    for state in ha_states:
        if state.get("entity_id") == entity_id:
            return entity_id, None, state.get("state")
    return entity_id, None, None


def _severity(enabled: bool | None, base: str) -> str:
    if enabled is False and base == "critical":
        return "warning"
    if enabled is False and base == "warning":
        return "info"
    return base


def _findings_for_item(
    *, kind: str, name: str, yaml_id: str | None, entity_id: str | None,
    enabled: bool | None, runtime_state: str | None, file: str, line: int | None, body: Any,
    control_mode: str,
) -> list[Finding]:
    text = _dump_text(body)
    lower_name = name.casefold()
    out: list[Finding] = []

    def add(code: str, base: str, reason: str, recommendation: str) -> None:
        out.append(Finding(
            code=code,
            severity=_severity(enabled, base),
            kind=kind,
            name=name,
            yaml_id=yaml_id,
            entity_id=entity_id,
            enabled=enabled,
            runtime_state=runtime_state,
            file=file,
            line=line,
            reason=reason,
            recommendation=recommendation,
        ))

    if name == "Elbil påmindelse kl. 21 og 23 hvis ikke lader / under mål":
        add("legacy_duplicate_ev_reminder", "warning",
            "Gammel 21/23-påmindelse overlapper den nyere Citroën-påmindelse og har tidligere brugt Minimum SOC som mål.",
            "Deaktivér eller slet den gamle påmindelse og behold kun den robuste version.")

    if name.startswith("EV Forvarmning - Husbond"):
        add("legacy_husband_preheat", "critical",
            "Gammel forvarmningsautomation er ikke længere relevant og har historisk sendt wake direkte.",
            "Hold den deaktiveret eller slet den. Add-on'en bør eje wake-politikken.")

    if name == "Stellantis - Keep-alive via update interval":
        add("legacy_stellantis_keepalive", "warning",
            "Keep-alive ændrer løbende Stellantis update interval og kan skabe ekstra trafik/wake-lignende aktivitet.",
            "Hold den deaktiveret. Brug provider-health og kontrolleret refresh i EV Orchestrator i stedet.")

    if "auto vælg bruger" in lower_name and "vagt" in lower_name:
        add("legacy_user_selector", "warning",
            "Kalenderbaseret bil/brugerlogik er ikke længere nødvendig, når Citroën ikke deles på samme måde.",
            "Hold den deaktiveret medmindre den fortsat har et konkret formål.")

    safe_wake_item = kind == "script" and name == "Citroën - sikker wake (anti-spam)"
    if CITROEN_WAKE in text and not safe_wake_item:
        add("direct_citroen_wake", "critical",
            "Sender Citroën wake direkte og omgår central 12V-beskyttelse/cooldown.",
            "Deaktivér eller omskriv så wake kun går gennem EV Orchestrator (eller det centrale safe-wake script under migrationen).")

    safe_reload_item = kind == "script" and name == "Citroën - reload Stellantis"
    if "homeassistant.reload_config_entry" in text and not safe_reload_item:
        add("direct_stellantis_reload", "warning",
            "Genindlæser config entry direkte og kan kollidere med andre recovery-forsøg.",
            "Centralisér reload i EV Orchestrator.")

    targetish = any(token in lower_name for token in ("mål", "target", "stop", "påmindelse", "pamindelse"))
    stopish = CITROEN_STOP in text or MG_SWITCH in text and "turn_off" in text
    if CITROEN_MIN in text and (targetish or stopish):
        if "number.set_value" not in text or stopish or "påmindelse" in lower_name or "pamindelse" in lower_name:
            add("citroen_minimum_soc_as_target", "critical",
                "Citroën EV Smart Charging Minimum SOC optræder i en mål/stop-kontekst. Minimum SOC er et sikkerhedsgulv, ikke normalt slutmål.",
                "Brug input_number.citroen_e_c4_onskede_batteri som normalt Target SOC.")

    if MG_MIN in text and (targetish or stopish):
        if "number.set_value" not in text or stopish:
            add("mg_minimum_soc_as_target", "critical",
                "MG EV Smart Charging Minimum SOC optræder i en mål/stop-kontekst. Minimum SOC er ikke normalt slutmål.",
                "Brug input_number.mg_s6ev_onskede_batteri som normalt Target SOC.")

    has_charge_actuator = CITROEN_START in text or CITROEN_STOP in text or MG_SWITCH in text
    if has_charge_actuator:
        if control_mode == "control":
            add("parallel_charge_controller", "critical",
                "Denne automation/script kan starte eller stoppe opladning samtidig med EV Orchestrator.",
                "Deaktivér den før EV Orchestrator sættes i Control mode.")
        elif control_mode == "monitor":
            add("future_charge_controller_overlap", "info",
                "Denne automation/script styrer opladning. Den kan blive en konflikt, når EV Orchestrator senere overtager Control mode.",
                "Ingen ændring kræves i Monitor mode; audit-listen bruges som migrationscheckliste.")

    return out


def scan(ha_states: list[dict[str, Any]], control_mode: str = "monitor") -> dict[str, Any]:
    findings: list[Finding] = []
    stats = {"automation_count": 0, "script_count": 0, "parse_errors": []}

    if AUTOMATIONS.exists():
        raw = AUTOMATIONS.read_text(encoding="utf-8", errors="replace")
        try:
            data = yaml.load(raw, Loader=LenientLoader) or []
            if not isinstance(data, list):
                raise ValueError("automations.yaml er ikke en liste")
            stats["automation_count"] = len(data)
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("alias") or "(uden alias)")
                yaml_id = str(item.get("id")) if item.get("id") is not None else None
                entity_id, enabled, runtime_state = _automation_entity(yaml_id, name, ha_states)
                line = _line_for(raw, f"alias: {name}") or _line_for(raw, name)
                findings.extend(_findings_for_item(
                    kind="automation", name=name, yaml_id=yaml_id, entity_id=entity_id,
                    enabled=enabled, runtime_state=runtime_state, file="automations.yaml", line=line, body=item,
                    control_mode=control_mode,
                ))
        except Exception as exc:
            stats["parse_errors"].append(f"automations.yaml: {exc}")

    if SCRIPTS.exists():
        raw = SCRIPTS.read_text(encoding="utf-8", errors="replace")
        try:
            data = yaml.load(raw, Loader=LenientLoader) or {}
            if not isinstance(data, dict):
                raise ValueError("scripts.yaml er ikke et mapping")
            stats["script_count"] = len(data)
            for key, body in data.items():
                if not isinstance(body, dict):
                    continue
                name = str(body.get("alias") or key)
                entity_id, enabled, runtime_state = _script_entity(str(key), ha_states)
                line = _line_for(raw, f"{key}:")
                findings.extend(_findings_for_item(
                    kind="script", name=name, yaml_id=str(key), entity_id=entity_id,
                    enabled=enabled, runtime_state=runtime_state, file="scripts.yaml", line=line, body=body,
                    control_mode=control_mode,
                ))
        except Exception as exc:
            stats["parse_errors"].append(f"scripts.yaml: {exc}")

    unique: dict[tuple[str, str | None, str], Finding] = {}
    for finding in findings:
        key = (finding.code, finding.yaml_id, finding.name)
        previous = unique.get(key)
        if previous is None:
            unique[key] = finding
        else:
            rank = {"critical": 3, "warning": 2, "info": 1}
            if rank[finding.severity] > rank[previous.severity]:
                unique[key] = finding

    findings = list(unique.values())
    rank = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda x: (rank.get(x.severity, 9), x.enabled is False, x.name))

    summary = {
        "critical": sum(1 for x in findings if x.severity == "critical"),
        "warning": sum(1 for x in findings if x.severity == "warning"),
        "info": sum(1 for x in findings if x.severity == "info"),
        "enabled_findings": sum(1 for x in findings if x.enabled is True),
    }
    return {"summary": summary, "stats": stats, "findings": [x.to_dict() for x in findings]}
