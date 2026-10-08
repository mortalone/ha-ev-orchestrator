# EV Orchestrator 0.3.0

EV Orchestrator is a central monitor and future charging controller for Home Assistant.

## 0.3.0

- Adds configurable **vehicle identity / safety interlocks**.
- Citroën can use a local BLE beacon as supporting identity evidence.
- MG exclusion uses selectable entities; defaults are `charger_connected` and `battery_charging`.
- A positive MG signal always blocks Citroën Clever fallback.
- Unknown or stale MG signals block fallback by default (**fail closed**).
- Identity evidence and verdicts are visible in Ingress.
- Adds design/settings for experimental Clever `power_required = 0 kWh` soft-stop.
- Stop verification is automatic from Home Assistant/Clever telemetry. The user is never expected to physically inspect the car or approve a stop.
- Keeps variable status-check intervals for Citroën command/wake observation.

## Clever fallback principle

Clever may become a fallback charger-controller when Citroën cloud control is degraded, but only when MG is safely excluded and Citroën is identified with sufficient evidence.

The optional Clever emulator is **not** required for departure time, `number.power_required`, or smart-charging/boost control. It is only required for Clever's additional live-session telemetry.

`power_required = 0 kWh` is treated as an experimental **soft-stop**, not a guaranteed hard relay command. When Control mode is implemented, the add-on will automatically verify success from signals such as house power/power drop, fresh Citroën charging state and Clever live charging state when available.

No manual confirmation is part of this design.

## Vehicle identity

The Ingress settings allow configuration of:

- Citroën BLE beacon entity and its present states,
- primary MG guard entity and states,
- MG charging entity and states,
- optional extra MG presence/location/Wi-Fi entity,
- maximum acceptable signal age,
- number of independent negative MG signals required before MG is considered excluded.

By default, an unknown/stale MG state blocks Clever fallback.

## Legacy audit

The add-on scans `/homeassistant/automations.yaml` and `/homeassistant/scripts.yaml` read-only and compares findings with live Home Assistant states.

## Safety

0.3.0 remains **Monitor Only**. It sends no vehicle, wake or Clever charging commands.
