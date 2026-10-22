"""INT1-A: default-off fake-only PX turn preflight (NOT provider execution).

This guards the opt-in *actual* bin/px-agent dispatch seam. It is intentionally
read-only and returns after required Hospital/Chart continuity validation,
before message persistence, broker launch or any model/tool operation.

Only the separately reviewed disposable INT1 fixture may invoke this mode.
INT1-B will supply atomic turn acceptance and durable revocation. Until then
there is deliberately NO way to execute a fake S3 turn through this interface.
"""
import os
from pathlib import Path

PROFILE = "EXEC_S3_FAKE_ONLY"
FAKE_ID = "int1-fake"
ENV_PATHS = {
    "PX_HOSPITAL_DB": "/fixture/hospital/data/hospital.db",
    "PX_HOSPITAL_DATA_DIR": "/fixture/hospital/data",
    "PX_AGENT_PROVIDER_CONFIG": "/fixture/providers/fake.json",
    "PX_AGENT_LOCK_DIR": "/fixture/locks",
    "PX_AGENT_AUTHORITY_DIR": "/fixture/authority",
    "HOME": "/fixture/home",
    "XDG_DATA_HOME": "/fixture/xdg/data",
    "XDG_CONFIG_HOME": "/fixture/xdg/config",
    "XDG_CACHE_HOME": "/fixture/xdg/cache",
    "XDG_RUNTIME_DIR": "/fixture/xdg/runtime",
    "TMPDIR": "/fixture/tmp",
}
ENV_STATIC = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "PYTHONDONTWRITEBYTECODE": "1",
}
ALLOWED_ENV = frozenset((*ENV_PATHS, *ENV_STATIC, "PWD"))

def require_fixture():
    """Fail before even allocating a turn lock or opening the Hospital DB."""
    env = dict(os.environ)
    if set(env) - ALLOWED_ENV:
        raise RuntimeError("INT1-A REFUSED // unexpected child environment")
    for key, value in {**ENV_PATHS, **ENV_STATIC}.items():
        if env.get(key) != value:
            raise RuntimeError("INT1-A REFUSED // untrusted fixture environment: " + key)
    if env.get("PWD", "/fixture") != "/fixture":
        raise RuntimeError("INT1-A REFUSED // untrusted working directory")
    fixture = Path("/fixture")
    if (not fixture.is_dir() or fixture.is_symlink() or
            not os.path.ismount(fixture) or not Path("/source/bin/px-agent").is_file()):
        raise RuntimeError("INT1-A REFUSED // OS fixture boundary absent")
    # Kernel mount records, not input claimed by the CLI or fake provider.
    try:
        records = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError as exc:
        raise RuntimeError("INT1-A REFUSED // kernel mount evidence unavailable") from exc
    mounts = {}
    for row in records:
        before = row.split(" - ", 1)[0].split()
        if len(before) > 5:
            mounts[before[4]] = before[5].split(",")
    if "/fixture" not in mounts or "rw" not in mounts["/fixture"]:
        raise RuntimeError("INT1-A REFUSED // fixture writable mount missing")
    for path in ("/source/bin/px", "/source/bin/px-agent",
                 "/source/bin/px-hospital-store",
                 "/source/bin/hospital_target_preflight.py",
                 "/source/bin/px_int1_fake_guard.py"):
        if path not in mounts or "ro" not in mounts[path]:
            raise RuntimeError("INT1-A REFUSED // trusted source mount missing")
    if Path("/etc/passwd").exists() or Path("/source/.git").exists():
        raise RuntimeError("INT1-A REFUSED // host surface exposed")
    return True

def require_profile(provider_id, record, registry):
    """Reject all real provider records and any fake provider command fields."""
    if (provider_id != FAKE_ID or not isinstance(record, dict) or
            record != {"name": "INT1 FAKE", "executionProfile": PROFILE,
                       "dialect": "exec-s3-fake-only"} or
            not isinstance(registry, dict) or
            registry.get("version") != 1 or
            registry.get("providers") != {FAKE_ID: record} or
            set(registry) != {"version", "providers"}):
        raise RuntimeError("INT1-A REFUSED // unsupported synthetic-only provider")
    return True

def require_doctor_room_binding(session, room):
    """I1: require the persisted session Doctor to own the persisted Room.

    Session creation in the Hospital store currently allows a different
    Doctor ID. Until a durable, separately verified succession grant exists,
    an opt-in synthetic preflight must fail closed on every mismatch.
    Check before retrieving the Room's HANDOFF and Chart context.
    """
    session_room = str(session.get("roomId") or "")
    room_id = str(room.get("id") or "")
    session_doctor = str(session.get("doctorId") or "")
    room_doctor = str(room.get("doctorId") or "")
    if not session_room.strip() or not room_id.strip() or session_room != room_id:
        raise RuntimeError("INT1-A REFUSED // DOCTOR_ROOM_LINK_MISMATCH")
    if not session_doctor.strip() or not room_doctor.strip():
        raise RuntimeError("INT1-A REFUSED // DOCTOR_ROOM_IDENTITY_UNRESOLVED")
    if session_doctor != room_doctor:
        raise RuntimeError("INT1-A REFUSED // DOCTOR_ROOM_MISMATCH")
    return True


def preflight_result(context, *, provider_id, room_id, bed_path, resume):
    """No prompt/context body emitted: proofs are summaries, not model traffic."""
    if (str(context["session"]["providerId"]) != provider_id or
            str(context["room"]["id"]) != room_id or
            str(context["session"]["roomId"]) != room_id or
            str(context["session"]["workingDirectory"]) != bed_path):
        raise RuntimeError("INT1-A REFUSED // identity changed during context assembly")
    return {
        "state": "PREFLIGHT_ONLY",
        "profile": PROFILE,
        "providerId": provider_id,
        "roomId": room_id,
        "resume": bool(resume),
        "contextVersion": context["version"],
        "requiredHandoffIds": [str(x["id"]) for x in context["requiredHandoffs"]],
        "approvedRoomChartIds": [str(x["id"]) for x in context["approvedRoomChart"]],
        "approvedPatientChartIds": [str(x["id"]) for x in context["approvedPatientChart"]],
        "messagesAccepted": 0,
        "eventsAccepted": 0,
        "brokerStarted": False,
        "modelCalls": 0,
        "toolCalls": 0,
        "productionReady": False,
    }
