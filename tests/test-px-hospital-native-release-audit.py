#!/usr/bin/env python3
"""Hospital protected release / writer inventory, disposable source tests.

Checks real PX command allowlist, simulated /proc open DB descriptors,
foreign-UID/old DB detection and fail-closed unknown processes. Never
inspects the operator's /proc, service, config or Hospital database.
"""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"bin"))
import px_hospital_native_release_audit as audit
import px_hospital_protected_store_bridge as routes

def held(cb,part):
    try:
        cb()
    except audit.AuditHold as exc:
        assert part in str(exc),(part,str(exc))
    else:
        raise AssertionError("MISSING_RELEASE_HOLD // "+part)

assert len(routes.READ_COMMANDS)==19
assert len(routes.WRITE_COMMANDS)==21
assert routes.route_coverage()
assert not (routes.READ_COMMANDS & routes.WRITE_COMMANDS)
assert not ((routes.READ_COMMANDS|routes.WRITE_COMMANDS)&routes.EXCLUDED_COMMANDS)
assert "init" in routes.EXCLUDED_COMMANDS
assert "room-lifecycle-trash" in routes.EXCLUDED_COMMANDS
assert "room-lifecycle-restore" in routes.EXCLUDED_COMMANDS

cfg={
    "schema":audit.SCHEMA,
    "writerUid":42010,
    "clientUid":42011,
    "runtimeUid":42012,
    "stateDirectory":"/var/lib/post-apollo/hospital",
    "socketDirectory":"/run/post-apollo/hospital/runtime",
}
assert audit._literal_json(b'{"schema":"example"}')=={"schema":"example"}
held(lambda:audit._literal_json(b'{"schema":"a","schema":"b"}'),
     "DUPLICATE_CONFIG_FIELD")
held(lambda:audit._literal_json(b'{"value":NaN}'),"NONFINITE_CONFIG")

with tempfile.TemporaryDirectory(prefix="hospital-process-audit-fixture-") as temp:
    root=Path(temp)
    proc=root/"proc"
    proc.mkdir()
    protected=root/"protected"/"hospital.db"
    protected.parent.mkdir()
    protected.write_bytes(b"DISPOSABLE_SQLITE_PLACEHOLDER")
    legacy=root/"desktop"/"hospital.db"
    legacy.parent.mkdir()
    legacy.write_bytes(b"DISPOSABLE_OLD_FILE")
    # The evaluator sees the path configured by the root-owned writer
    # contract. For this synthetic /proc tree the owner directory is a
    # disposable path; no operator path or permissions are changed.
    config=dict(cfg,stateDirectory=str(protected.parent))
    def process(pid,uid,source,flags="0100002"):
        p=proc/str(pid)
        (p/"fd").mkdir(parents=True)
        (p/"fdinfo").mkdir()
        (p/"status").write_text("Name:\tpython3\n"
            f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        (p/"fd"/"3").symlink_to(source)
        (p/"fdinfo"/"3").write_text(f"pos:\t0\nflags:\t{flags}\n")
        return p

    expected=process(101,42010,protected)
    observed,unknown,checked=audit.scan_open_hospital_descriptors(proc)
    assert len(observed)==1 and unknown==0 and checked==1
    assert observed[0]["uid"]==42010
    assert observed[0]["access"]==os.O_RDWR
    assert observed[0]["target"]==str(protected)
    result=audit.assess_writers(config,observed,unknown,checked)
    assert result["oldOrForeignDatabaseObserved"] is False
    # A zero-collision scan is NOT an activation or old-program fence.
    assert result["externalWritersStopped"] is False
    assert result["oldLaunchPathsFenced"] is False
    assert result["verifiedBackupAndRollback"] is False
    assert result["releaseApproved"] is False

    desktop=process(102,42011,legacy)
    observed,unknown,checked=audit.scan_open_hospital_descriptors(proc)
    assert checked==2 and len(observed)==2 and unknown==0
    collision=audit.assess_writers(config,observed,unknown,checked)
    assert collision["oldOrForeignDatabaseObserved"] is True
    assert collision["unapprovedHospitalDescriptorCount"]==1

    # Unapproved desktop process with a handle to the *protected* DB
    # still violates owner-only storage and must refuse.
    desktop.joinpath("fd","3").unlink()
    desktop.joinpath("fd","3").symlink_to(protected)
    observed,unknown,checked=audit.scan_open_hospital_descriptors(proc)
    mismatch=audit.assess_writers(config,observed,unknown,checked)
    assert mismatch["unapprovedHospitalDescriptorCount"]==1

    # An inaccessible /proc/fdinfo scan must NOT certify quiet writers.
    desktop.joinpath("fdinfo","3").unlink()
    observed,unknown,checked=audit.scan_open_hospital_descriptors(proc)
    assert unknown==1
    held(lambda:audit.assess_writers(config,observed,unknown,checked),
         "INCOMPLETE_LIVE_PROCESS_INVENTORY")

    # If a process exits between listing and read, the result is still
    # incomplete. A fresh quiesced scan, not guesswork, is required.
    desktop.joinpath("status").unlink()
    observed,unknown,checked=audit.scan_open_hospital_descriptors(proc)
    assert unknown>=1
    held(lambda:audit.assess_writers(config,observed,unknown,checked),
         "INCOMPLETE_LIVE_PROCESS_INVENTORY")
    held(lambda:audit.assess_writers(config,[],0,0),
         "INCOMPLETE_LIVE_PROCESS_INVENTORY")

# Production CLI refuses ordinary user, arbitrary root config overrides
# and missing root-controlled policy. CI never scans real /proc.
result=subprocess.run(
    [sys.executable,str(ROOT/"bin"/"px_hospital_native_release_audit.py"),
     "--fake-clean"],
    text=True,capture_output=True,timeout=10)
assert result.returncode!=0
assert "HOSPITAL_RELEASE_HOLD" in result.stderr
assert "releaseApproved" not in result.stdout

print("HOSPITAL NATIVE RELEASE AUDIT // PASS // 21 writes/19 reads, protected/old descriptor collision, incomplete proc fails closed, NO LIVE INSTALL")
