#!/usr/bin/env python3
"""H1: a root-controlled native cutover marker denies the old desktop DB path.

All paths are disposable test fixtures. The test DOES NOT install the marker,
touch /etc or the user's Hospital, create a service, or authorize a cutover.
The protected owner runtime must remain capable of using an injected SQLite
connection: only direct legacy connect() is blocked after a marker exists.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_protected_store_bridge as bridge

def load_legacy():
    path = ROOT / "bin" / "px-hospital-store"
    loader = importlib.machinery.SourceFileLoader("_h1_cutover_store_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

def denied(action, reason):
    try:
        action()
    except RuntimeError as exc:
        assert reason in str(exc), "UNEXPECTED_GUARD_REFUSAL"
    else:
        raise AssertionError("UNPROTECTED_DESKTOP_SQLITE_OPEN_AFTER_CUTOVER")

store = load_legacy()
assert str(store.LEGACY_CUTOVER_MARKER) == (
    "/etc/post-apollo/hospital/legacy-store-cutover.v1"
)
with TemporaryDirectory(prefix="hospital-h1-cutover-only-") as temporary:
    base = Path(temporary)
    marker = base / "cutover.v1"
    old_db = base / "old" / "hospital.db"
    override_db = base / "override" / "hospital.db"
    env = {
        "PX_HOSPITAL_DB": str(old_db),
        "PX_HOSPITAL_DATA_DIR": str(base / "old"),
    }
    with patch.dict(os.environ, env), patch.object(
        store, "LEGACY_CUTOVER_MARKER", marker
    ):
        # Before cutover, source-level compatibility is unchanged.
        with store.connect() as db:
            assert store.migrate(db) == 12
        assert old_db.is_file()

        # A present marker fails closed regardless of contents or file type.
        for create in ("file", "dangling-symlink", "directory"):
            if create == "file":
                marker.write_text("not an authorization receipt")
            elif create == "dangling-symlink":
                marker.symlink_to(base / "nonexistent-target")
            else:
                marker.mkdir()
            denied(store.connect, "HOSPITAL_NATIVE_PROTECTED_RUNTIME_REQUIRED")
            assert old_db.is_file()
            if marker.is_dir() and not marker.is_symlink():
                marker.rmdir()
            else:
                marker.unlink()

        marker.write_text("fixture")
        # A caller-supplied different SQLite path is NOT an escape.
        with patch.dict(os.environ, {"PX_HOSPITAL_DB": str(override_db)}):
            denied(store.connect, "HOSPITAL_NATIVE_PROTECTED_RUNTIME_REQUIRED")
        assert not override_db.exists()
        assert not override_db.parent.exists()

        # A failed marker status check is a HOLD, never fallback to SQLite.
        with patch.object(Path, "lstat", side_effect=PermissionError("fixture")):
            denied(store.connect, "HOSPITAL_LEGACY_CUTOVER_STATE_UNVERIFIABLE")
        # A mutable client environment name cannot override this fixed path.
        with patch.dict(os.environ, {"PX_HOSPITAL_CUTOVER_MARKER": str(base/"absent")}):
            denied(store.connect, "HOSPITAL_NATIVE_PROTECTED_RUNTIME_REQUIRED")

    # The protected writer imports the same PX functions and receives an
    # owner-held connection; its 19 read and 21 write routes must NOT call
    # the forbidden desktop connect(). The four unmerged commands stay held.
    protected_db = base / "protected-owner.db"
    with sqlite3.connect(protected_db) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        assert bridge._store.migrate(db) == 12
        with patch.object(bridge._store, "LEGACY_CUTOVER_MARKER", marker):
            assert bridge.route_coverage()
            response = bridge.execute(db, ["status"])
            assert response["schema_version"] == 12
            bridge.execute(db, ["doctor-put", "fixture-doctor", "--name", "Fixture Doctor"])
            assert db.execute(
                "SELECT count(*) FROM doctors WHERE doctor_id='fixture-doctor'"
            ).fetchone()[0] == 1
            for command in (
                "session-attach-atomic",
                "session-succeed-atomic",
                "room-bed-claim-atomic",
                "room-bed-claim-signed-atomic",
            ):
                try:
                    bridge.parse_argv([command])
                except bridge.StoreCommandHold as exc:
                    assert str(exc) == "COMMAND_NOT_EXPOSED"
                else:
                    raise AssertionError("UNREVIEWED_H1_WRITE_ENABLED")

print(
    "PX H1 CUTOVER FENCE // PASS // existing legacy direct SQLite held after "
    "fixed marker; protected 21 writes/19 reads unaffected; four new commands "
    "denied; NO LIVE HOST CHANGE"
)
