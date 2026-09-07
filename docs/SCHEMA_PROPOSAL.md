# RFC: a reference wireless schema for the Infrahub schema library

**Status:** draft for discussion · **Author:** Jonathan Finney · **Implemented in:** `schema/nocternal_wireless.yml`

## Problem

Infrahub's base schemas model the parts of a network that have config files: devices, interfaces, IPAM, circuits.
Enterprise wireless is the largest device population in most campuses and hospitals — often 5–10 APs per switch —
and it is almost entirely cloud-managed (Meraki, Mist, Aruba Central, Catalyst Center). There is no running-config
to render into an artifact, no CLI to diff, and the vendor dashboards are each their own source of truth. The
result is that wireless intent lives in spreadsheets, Ekahau projects, and people's heads, and nobody can answer
"what is this site *supposed* to be broadcasting" without logging into a dashboard and trusting it.

That is precisely the gap a schema-driven source of truth exists to close. This RFC proposes a small,
vendor-neutral wireless schema that maps cleanly onto every major cloud-managed platform, with vendor specifics
kept out of the core nodes.

## Design goals

1. **Vendor-neutral core, vendor-specific edges.** The four platforms above agree on the nouns — site, access
   point, SSID, RF profile — and disagree on everything else. The core carries only the fields all four share;
   vendor detail lives in a `JSON` attribute or a vendor-namespaced extension node.
2. **Intent, not inventory.** Every node describes what *should* be true. `lifecycle` on an AP is the expected
   state right now (`planned`, `staged`, `in_service`, `decommissioned`), which is what lets a monitoring system
   grade a missing device as "expected" or "outage".
3. **Join keys to observed state are first-class.** `WirelessAccessPoint.serial` and `WirelessSite.<vendor>_network_id`
   exist so that an external system can line intent up against a dashboard API without name-matching heuristics.
4. **Security posture is explicit.** `auth_mode` is a constrained dropdown (`open` / `psk` / `ipsk` / `dot1x`), so
   a Proposed Change that downgrades a clinical SSID from `dot1x` to `psk` is a visible, reviewable diff — and a
   check can refuse it.
5. **Cheap to adopt.** Three nodes. A site can be bootstrapped from a dashboard in one API read, then corrected.

## Proposed nodes (namespace `Wireless`)

| Node | Purpose | Key attributes | Relationships |
|---|---|---|---|
| `WirelessSite` | One managed WLAN estate; usually 1:1 with a vendor "network" or "site" | `name` (unique), `vertical` (healthcare / venue / retail / office …), `sla_tier` (critical / standard / best_effort), `timezone`, `address`, `meraki_network_id` · `mist_site_id` · `central_group` (optional join keys) | `access_points` (Component, many), `ssids` (Component, many), `rf_profiles` (many) |
| `WirelessAccessPoint` | An AP that is supposed to exist at a site | `serial` (unique), `name`, `model`, `mac`, `mgmt_ip`, `floor`, `lifecycle` (planned / staged / in_service / decommissioned), `tags` | `site` (Parent), `rf_profile` (one, optional) |
| `WirelessSSID` | An SSID that is supposed to be broadcast at a site | `name`, `number` (vendor slot), `enabled`, `hidden`, `auth_mode` (open / psk / ipsk / dot1x), `vlan_id`, `band` (dual / five_only / six_capable), `client_isolation` | `site` (Parent); unique per `(site, name)` |
| `WirelessRFProfile` *(proposed)* | A named RF standard applied to APs | `name`, `band_steering`, `min_bitrate_24`, `min_bitrate_5`, `tx_power_5_max`, `channel_width_5`, `six_ghz_enabled`, `dfs_allowed` | `sites` (many) |

Everything vendor-specific — Meraki `rfProfileId`, Mist `wlan_id`, Aruba Central `group`, Catalyst `policy tag` —
goes in a `vendor: JSON` attribute on the relevant node. It stays queryable, stays diffable, and never forces a
schema change when a vendor adds a knob.

The implementation in this repo covers the first three nodes; `WirelessRFProfile` is modelled today via Infrahub
**Profiles** on `WirelessAccessPoint` (`Office-5G-Pref`, `Clinical-Dense`), which is enough for intent. The
dedicated node earns its place once RF parameters need to be rendered into per-vendor API calls.

## Vendor mapping

| Concept | Meraki | Mist | Aruba Central | Catalyst Center |
|---|---|---|---|---|
| Site | Network (`N_…`) | Site | Group / Site | Site (area/building/floor) |
| AP identity | serial | serial / MAC | serial | serial |
| AP lifecycle | claimed → online | assigned → connected | provisioned → up | assigned → reachable |
| SSID | `ssids[number]` | `wlans[]` | WLAN in group | WLAN profile + policy tag |
| auth_mode | `authMode` | `auth.type` | `essid.opmode` | security type |
| vlan | `defaultVlanId` | `vlan_id` | `vlan` | interface / VLAN |
| RF profile | `rfProfiles` | `rf templates` | `radio profiles` | RF profile |
| Rogue / evil twin | Air Marshal | Rogue APs | WIDS | aWIPS |

The "observed" side of each column is what a monitoring platform reads; the schema is what it compares against.

## What the schema enables (all implemented here)

- **Drift**: `drift.py` — intent from Infrahub, observed from the dashboard API or a NOC's own store; typed findings
  (`MISSING`, `UNEXPECTED`, `DOWN`, `DEGRADED`, `SSID_UNEXPECTED`, `EVIL_TWIN`, `ROGUE`, …).
- **Pre-change readiness**: run drift against a *branch* to see what will be outstanding after merge.
- **Checks**: a Proposed Change fails when live reality disagrees with the proposed intent.
- **Artifacts**: the SSID set rendered as the vendor API calls that would enforce it.
- **Generators**: a site's `vertical` produces its standard SSID set.
- **Design → intent**: Ekahau simulated APs become `lifecycle: planned` nodes with floor and model.

## Open questions for the schema library

1. Should `WirelessSite` be its own node or a set of attributes/relationships on `LocationSite` from the base
   location schema? (Preference: own node with a relationship to `LocationSite` — a site can have several WLAN
   estates, e.g. clinical and guest on separate dashboards.)
2. Is a per-vendor extension namespace (`WirelessMerakiAP` inheriting a `WirelessGenericAP`) better than a `JSON`
   attribute once more than one vendor is live in the same instance? Generics would give typed, filterable vendor
   fields at the cost of schema churn.
3. Where do PSKs and RADIUS secrets live? Not in the schema — the artifact template leaves `${...}` placeholders.
   A pointer to an external secret (`secret_ref`) on `WirelessSSID` may be worth standardising.
4. Should `WirelessRFProfile` be a node from day one, or arrive with the first multi-vendor artifact?

Feedback welcome — open an issue on this repo or comment on the schema file directly.
