#!/usr/bin/env python3
"""H1: read-only, cross-repository *source* caller inventory.

Uses only exact CI-checked-out Hospital UI source and PX source; does not
execute a launcher, open SQLite, inspect a host, or authorize deployment.
This is an evidence witness, NOT a complete live process/launcher inventory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "hospital-ui-source"
SERVICES = UI / "services" / "hospital"
REQUIRED_LEGACY = {
    "HospitalDoctorService.qml",
    "HospitalAssignmentService.qml",
    "HospitalChartService.qml",
    "HospitalWorkforceRoomCreateService.qml",
}
REQUIRED_NATIVE = {
    "HospitalRoomLifecycleService.qml",
    "HospitalRoomBinService.qml",
}
LEGACY_PATHS = (
    ".local/share/post-apollo-dev-runtime/bin/px",
    ".local/bin/px",
)

assert os.environ.get("GITHUB_ACTIONS") == "true"
assert os.environ.get("CI") == "true"
assert SERVICES.is_dir(), "PINNED_HOSPITAL_UI_CHECKOUT_REQUIRED"
assert (ROOT / "bin/px").is_file()
assert (ROOT / "bin/px-hospital-store").is_file()

# Inventory every QML service in the pinned UI checkout instead of making
# the observed list itself the input. New direct desktop call sites must be
# exposed in the CI output, not disappear behind a short curated list.
legacy = {}
native = []
for path in sorted(SERVICES.rglob("*.qml")):
    source = path.read_text(encoding="utf-8")
    name = str(path.relative_to(SERVICES))
    if any(fragment in source for fragment in LEGACY_PATHS):
        commands = sorted(set(re.findall(
            r'''["']hospital["']\s*,\s*["']([a-z][a-z0-9-]*)["']''',
            source,
        )))
        legacy[name] = commands
    if "/usr/libexec/post-apollo/hospital/hospital-room-" in source:
        native.append(name)

assert REQUIRED_LEGACY <= set(legacy), "KNOWN_UNMIGRATED_UI_CALLER_DISAPPEARED"
assert REQUIRED_NATIVE <= set(native), "PROTECTED_ROOM_UI_CALLER_DISAPPEARED"
assert all(
    all(route in LEGACY_PATHS for route in LEGACY_PATHS)
    for _name in REQUIRED_LEGACY
)
px = (ROOT / "bin/px").read_text(encoding="utf-8")
px_legacy = re.findall(
    r'python3\s+"\$ROOT/bin/px-hospital-store"',
    px,
)
assert len(px_legacy) >= 4, "PX_LEGACY_FRONT_DOOR_CHANGED"
assert 'hospital)' in px and '"$@"' in px, "PX_HOSPITAL_ROUTER_CHANGED"
old_store = (ROOT / "bin/px-hospital-store").read_text(encoding="utf-8")
launcher = (ROOT / "bin/px-hospital-room-writerd").read_text(encoding="utf-8")
assert "refuse_legacy_store_after_cutover()" in old_store
assert "require_native_cutover_marker()" in launcher

# These UI callers run under the desktop user and currently choose a
# desktop-local px executable. The protected 21-write/19-read socket
# requires a distinct runtime UID. A direct desktop-to-store-command
# substitute would violate its authority boundary, not fix this gap.
# This result is intentionally immutable, deny-only release evidence.
report = {
    "schema": "postapollo.hospital.h1-source-caller-inventory.v1",
    "uiCheckout": "hospital-ui-source",
    "uiServiceScope": "services/hospital/**/*.qml",
    "legacyPxServiceCount": len(legacy),
    "legacyPxServices": legacy,
    "protectedRoomServiceCount": len(native),
    "protectedRoomServices": sorted(native),
    "pxDirectStoreCallSites": len(px_legacy),
    "knownLegacyWriteSurfaces": sorted(REQUIRED_LEGACY),
    "allWriterCompatibilityVerified": False,
    "installedHostObserved": False,
    "oldBinariesAndLaunchersFenced": False,
    "protectedRuntimeRoutingAccepted": False,
    "releaseApproved": False,
}
assert report["legacyPxServiceCount"] >= len(REQUIRED_LEGACY)
assert not report["releaseApproved"]
print(json.dumps(report, sort_keys=True, separators=(",", ":")))
print(
    "HOSPITAL H1 SOURCE CALLER INVENTORY // PASS // old UI launchers "
    "identified; installed host NOT verified; RELEASE HOLD"
)
