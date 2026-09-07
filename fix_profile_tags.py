#!/usr/bin/env python3
"""
fix_profile_tags.py — workaround for an Infrahub 1.11.2 bug: a List attribute (`tags`) inherited from a Profile
comes back as a string. The SDK then fails to upsert ("String! used in position expecting GenericScalar") and
the UI crashes opening the node ("n?.map is not a function" in getObjectItemDisplayValue).

Clears `tags` on every ProfileWirelessAccessPoint on the given branches so nothing inherits a List.
    python3 fix_profile_tags.py                         # main
    python3 fix_profile_tags.py main nash-6ghz-refresh  # main + a branch (branches keep their own copy)
"""
import sys

from infrahub_sdk import InfrahubClientSync

client = InfrahubClientSync()
for branch in (sys.argv[1:] or ["main"]):
    profiles = client.all(kind="ProfileWirelessAccessPoint", branch=branch)
    for p in profiles:
        print(f"{branch}: {p.profile_name.value:<18} tags={p.tags.value!r} ({type(p.tags.value).__name__})", end="  ")
        if p.tags.value in (None, [], ""):
            print("already clear")
            continue
        p.tags.value = None
        p.update()
        print("-> cleared")
