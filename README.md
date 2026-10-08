# Home Assistant EV Orchestrator

Home Assistant add-on repository for **EV Orchestrator**.

Current version: **0.3.0**

EV Orchestrator centralizes EV monitoring, legacy-audit, provider health, vehicle identification/interlocks and future charging control for Citroën, MG and a Clever home charger.

## Current status

Version 0.3.0 is deliberately **Monitor Only**. It does not send START/STOP/WAKE or Clever commands yet. The purpose is to validate data quality, identify legacy automation conflicts and prove the safety interlocks before Control mode is enabled.

## Highlights

- Home Assistant Ingress UI.
- Citroën and MG telemetry health/freshness.
- EV Smart Charging remains available as planner.
- Clever integration support without requiring the emulator for schedule/energy control.
- Configurable Citroën BLE beacon and MG presence/charging interlocks.
- Fail-closed policy: unknown/stale MG state blocks Citroën Clever fallback.
- Automatic stop-verification design using HA/Clever signals; no manual confirmation is required.
- Legacy audit of `automations.yaml` and `scripts.yaml`.

Add this repository to the Home Assistant add-on store as a custom repository.
