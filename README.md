# nocternal-infrahub

**Intended wireless state in [Infrahub](https://github.com/opsmill/infrahub). Observed wireless state from a NOC's collectors. The diff is the drift report.**

Infrahub is a source of truth for what the network is *supposed* to be. A monitoring platform knows what it
*actually* is. Nobody owns the seam between them, and that seam is where every rogue AP, every leftover
`Setup-Temp` SSID, every "who renamed that access point" lives. This repo is a small, working bridge across it
for cloud-managed wireless (Meraki first; the schema is vendor-neutral).

```
        intent (should be)                                     observed (is)
  ┌────────────────────────┐                          ┌───────────────────────────┐
  │  Infrahub              │  GraphQL / Python SDK    │  NOCternal event store    │  SQLite
  │  WirelessSite          │ ───────────┐  ┌───────── │   device_state            │
  │  WirelessAccessPoint   │            │  │          │   rogue_aps (Air Marshal) │
  │  WirelessSSID          │            ▼  ▼          │   client_info             │
  └────────────────────────┘        ┌──────────┐      └───────────────────────────┘
        branches / proposed changes │ drift.py │            — or — Meraki Dashboard API
                                    └──────────┘
                                         │  report + JSON + exit code
                                         ▼
                        !! crit EVIL_TWIN   NOCternal-Corp   our SSID from a BSSID we don't own (on the WIRE)
```

## What's here

| File | Purpose |
|---|---|
| `schema/nocternal_wireless.yml` | Infrahub schema: `WirelessSite`, `WirelessAccessPoint`, `WirelessSSID` — lifecycle, auth mode, band, VLAN, SLA tier. Loads clean on Infrahub 1.11. |
| `seed_site.py` | Loads a site's intended state into Infrahub through the Python SDK. Idempotent; `--branch` aware. |
| `drift.py` | The engine. Intent from Infrahub (any branch) or JSON; observed from NOCternal's SQLite store, the Meraki API, or JSON. Prints a report, writes JSON, exits 1 on drift. |
| `bootstrap_intent.py` | Day-one intent from what already exists — from the Meraki API or from NOCternal's `device_state`. Edit the result; that edit *is* your intent. |
| `queries/site_intent.gql` | The GraphQL query on its own, for the Infrahub sandbox. |
| `fixtures/` | A synthetic 7-AP / 3-SSID site (`NASH-HQ`) as intended, as the dashboard reports it (nine planted faults), and as a future 6 GHz refresh. |
| `setup_mac.sh` | Docker engine on a Mac without Docker Desktop (Colima via Homebrew). |
| `demo.sh` / `demo_branch.sh` | Infrahub up → schema → seed → drift, then the branch scenario. |

## Run it in ten seconds (no Infrahub, no Meraki)

```
python3 drift.py --site NASH-HQ --intent fixtures/intent_nash_hq.json --observed fixtures/observed_nash_hq.json
```

```
NOCternal drift report — site NASH-HQ   intent: file:intent_nash_hq.json@main   observed: file:observed_nash_hq.json
================================================================================================
!! crit DOWN            NASH-HQ-AP-2F-03             intent in_service, dashboard says offline
!! crit EVIL_TWIN       NOCternal-Corp               our SSID name broadcast from a BSSID we don't own: 02:11:22:33:44:55 (seen on the WIRE)
!! crit MISSING         NASH-HQ-AP-2F-05             in intent as in_service but NOT in the dashboard
!! crit SSID_UNEXPECTED Setup-Temp                   broadcasting (psk, vlan 1) with no entry in intent
 ! warn MISMATCH        NASH-HQ-AP-2F-04.model       intent='MR57' observed='MR46'
 ! warn MISMATCH        NASH-HQ-AP-2F-04.name        intent='NASH-HQ-AP-2F-04' observed='nash-ap-2f-4'
 ! warn UNEXPECTED      MR33-spare                   MR33 Q2XX-OLD0-0099 is in the dashboard but not in the source of truth
   info NEIGHBOR        xfinitywifi                  foreign SSID from a0:b1:c2:d3:e4:f5, not on our wire
   info PLANNED         NASH-HQ-AP-3F-07             planned in intent, not claimed yet (expected)
------------------------------------------------------------------------------------------------
4 critical, 3 warning, 2 info   ->   DRIFT
```

Every line is something a wireless engineer has chased at 2 a.m. The point of the project is that each one is
now a *typed* finding (`kind`, `severity`, `object`, `intent`, `observed`) that a NOC can ticket, and that the
"intent" side lives somewhere with branches, diffs, and review.

## Run it against a real Infrahub

```
./setup_mac.sh        # Mac only: Colima + docker CLI, no Docker Desktop. Skip if you have Docker.
./demo.sh             # compose up (Infrahub 1.11 CE) → schema load → seed NASH-HQ → drift
```

Then open `http://localhost:8000` (`admin` / `infrahub`). The **Wireless** section in the left menu — Sites,
Access Points, SSIDs — was generated from the YAML. `http://localhost:8000/graphql` with
`queries/site_intent.gql` and `{"site": "NASH-HQ"}` shows the query `drift.py` runs.

### The part that needs Infrahub: drift against a *future* intent

```
./demo_branch.sh
```

Creates branch `nash-6ghz-refresh`, seeds a refreshed intent onto it (NOCternal-Corp goes `six_capable`, the
planned CW9166 goes `in_service`), and diffs today's reality against the branch:

```
!! crit MISSING         NASH-HQ-AP-3F-07             in intent as in_service but NOT in the dashboard
 ! warn SSID_MISMATCH   NOCternal-Corp.band          intent='six_capable' observed='five_only'
5 critical, 4 warning, 1 info   ->   DRIFT
```

That is a pre-change readiness check: what will be wrong *after* we merge, before we touch anything. Open the
branch in Infrahub, create a Proposed Change, and the diff shows exactly the two objects that moved. Merge, re-run,
and the CW9166 goes from `PLANNED (info)` to `MISSING (crit)` — the plan became outstanding work.

## The integration: observed state from the NOC's own store

`drift.py --nocternal <events.db>` reads NOCternal's SQLite event store directly — no Meraki call:

| NOCternal table | Becomes |
|---|---|
| `device_state` (serial, name, model, status) | access points, with `online / alerting / dormant / offline` → `DEGRADED` / `DOWN` |
| `rogue_aps` (ssid, bssid, on_wire, is_spoof, triage) | Air Marshal: `EVIL_TWIN`, `ROGUE`, `NEIGHBOR` — rows triaged `known-innocent` are skipped |
| `client_info` (ssid per associated client) | evidence of what is really broadcasting; an intent SSID with no clients is `SSID_QUIET (info)`, not a false `SSID_MISSING` |

```
python3 bootstrap_intent.py --from-nocternal ../noc-platform/events.db --network "Site - wireless,Site - 60019" --site SITE
python3 seed_site.py fixtures/intent_site.json
python3 drift.py --site SITE --nocternal ../noc-platform/events.db
```

`--network` takes a comma-separated list because Meraki sites are usually split across several dashboard
networks and each collector keys on the one it polls. The list is stored on the `WirelessSite` as
`nocternal_network`, so after seeding you only pass `--site`.

Swap `observed_from_nocternal()` for a read of your own monitoring store — the return shape is a dozen lines and
deliberately looks like what a Meraki poller already keeps.

## Schema notes

Three nodes, all in namespace `Wireless`. `WirelessAccessPoint.serial` is the join key to observed state;
`WirelessSSID` is unique per `(site, name)`. `lifecycle` (`planned / staged / in_service / decommissioned`) is
what turns a missing AP into either `PLANNED (info)` or `MISSING (crit)`. `sla_tier: critical` promotes a down AP
from warning to critical — a clinical floor and a break room are not the same outage.

Vendor-specific detail (Meraki RF profile IDs, Mist site IDs, Aruba Central group names) belongs in a `JSON`
attribute or a vendor-namespaced extension, not in these nodes.

## Where this goes next

- **Drift as an Infrahub Check** — wrap `compare()` in `InfrahubCheck` so a Proposed Change fails CI when live
  drift would remain after merge.
- **Generators** — a `SiteWirelessGenerator` that stamps a vertical's standard SSID set (clinical `dot1x`, guest
  `open`, biomed `ipsk`) onto every new `WirelessSite` with `vertical: healthcare`.
- **Multi-vendor observed adapters** — Mist, Aruba Central, Catalyst Center all reduce to devices + statuses +
  SSIDs + rogues.
- **MSP tenancy** — a `Customer` node above `Site`; branch-per-customer plus object permissions.

## License

MIT — see `LICENSE`.
