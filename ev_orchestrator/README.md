# EV Orchestrator 0.3.1

EV Orchestrator is a central monitor and future charging controller for Home Assistant.

## 0.3.1

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

0.3.1 remains **Monitor Only**. It sends no vehicle, wake or Clever charging commands.


## 0.3.8 diagnostics

- Shows **Seneste kontakt** and the HA entity that supplied the freshest vehicle signal for both cars.
- Shows Clever **Sidst set alder** from the integration's explicit last-seen timestamp.
- Adds an **AI diagnostic dump** with current snapshot, settings, provider/entity discovery, legacy audit, timeline events, relevant Home Assistant states and the add-on's internal application log.
- The diagnostic dump redacts common sensitive attributes such as passwords, API keys, tokens and GPS coordinates.
- Adds **Kopiér AI-dump** and **Hent AI-dump** buttons in Ingress.
- Tightens Clever auto-discovery so generic entities such as Status/Online/Charging must belong to the same charger entity prefix; this prevents unrelated devices from being selected.


## 0.3.8 legacy rollback

- Captures a persistent **legacy rollback baseline** on first start after upgrade.
- The baseline stores ON/OFF state for EV-related Home Assistant automations and is not overwritten automatically.
- Adds **Gendan legacy baseline** to restore the saved automation states if EV Orchestrator control is later rolled back.
- Adds a deliberate **Opdater baseline til nu** action with confirmation.
- Legacy audit details are collapsed by default while critical/warning/info statistics remain visible.
- Legacy entries are explicitly labeled as legacy/migration items.


## 0.3.8 polling clarification

- Renames **Seneste kontakt** to **Seneste HA-opdatering** because this value reflects Home Assistant state freshness, not a guaranteed direct vehicle-cloud contact.
- Renames **Health** in vehicle cards to **Data health**.
- Shows **Bil-polling: INGEN** in the System card.
- Monitor mode reads only Home Assistant's cached state registry. It does not call `homeassistant.update_entity`, vehicle refresh, wake, start or stop.
- The default 5-second loop is only a local Home Assistant state read and does not create extra 12V load on either vehicle.


## 0.3.8 vehicle contact evidence

- Adds **Sidste positive bilkontakt** as a separate concept from ordinary Home Assistant state freshness.
- Uses provider/vehicle timestamps exposed inside entity attributes when available.
- Treats a completed Citroën remote command as high-confidence positive contact.
- Shows **Forventet bilsvar** and flags a pending Citroën command as overdue after 180 seconds.
- Keeps **Seneste HA-opdatering** separately, so HA state activity is never confused with proven vehicle contact.
- Fixes the UI health color for providers whose state is `available` (including Clever).


## 0.3.8 SOC/report freshness

- Separates **SOC senest rapporteret** from **SOC værdi sidst ændret**.
- Telemetry health now uses Home Assistant's `last_reported` timestamp when available.
- A stationary vehicle whose SOC remains unchanged is therefore no longer marked stale merely because the numerical SOC value has not moved.
- Positive vehicle contact remains a separate signal and does not generate any extra vehicle polling.
