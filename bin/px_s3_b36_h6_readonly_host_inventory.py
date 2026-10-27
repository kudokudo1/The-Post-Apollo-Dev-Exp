#!/usr/bin/env python3
"""B36-H6 opt-in READ-ONLY Linux suitability inventory, never an admission grant.

No subprocesses, sockets, network, writes, Hermes, credentials, service API,
personal config, process enumeration or dynamically supplied file paths.
By default main() refuses host inspection. '--host-readonly' is a separately
reviewable explicit opt-in on the target machine; it is NEVER called by CI.
Report contains only allowlisted booleans, enums and fixed diagnostic codes.
A snapshot, including a real one, is NOT trusted OS attestation.
"""
import json
import os
import re
import stat
import sys

SCHEMA = "B36_H6_LINUX_HOST_READONLY_INVENTORY_V1"
MAX_SOURCE_CHARS = 262144
HOST_SOURCES = {
    "mountinfo": "/proc/self/mountinfo",
    "selfCgroup": "/proc/self/cgroup",
    "controllers": "/sys/fs/cgroup/cgroup.controllers",
    "status": "/proc/self/status",
    "unprivilegedUserns": "/proc/sys/kernel/unprivileged_userns_clone",
    "maxUserns": "/proc/sys/user/max_user_namespaces",
    "osRelease": "/etc/os-release",
    "selinuxEnforce": "/sys/fs/selinux/enforce",
}
NAMESPACE_KINDS = ("user", "mnt", "pid", "net", "cgroup")
KNOWN_CONTROLLERS = frozenset(("cpu", "cpuset", "io", "memory", "pids", "rdma", "hugetlb", "misc"))
TOOLS = {"bwrap": "/usr/bin/bwrap", "unshare": "/usr/bin/unshare",
         "systemdRun": "/usr/bin/systemd-run"}
SNAPSHOT_KEYS = frozenset(("sources", "namespaces", "tools", "userBusSocket"))
REASONS = ("NO_TRUSTED_HOSPITAL_AUTHORITY",
           "NO_AUTHENTICATED_HERMES_STOP_PROTOCOL",
           "NO_TRUSTED_KERNEL_DESCENDANT_ATTESTATION",
           "NATIVE_TOOLS_AND_CREDENTIAL_ISOLATION_UNVERIFIED",
           "REAL_PROVIDER_PRODUCTION_HOLD")


def _safe_source(value):
    return value if type(value) is str and len(value) <= MAX_SOURCE_CHARS else None


def _mount_v2(raw):
    if raw is None:
        return None
    for line in raw.splitlines():
        if " - " not in line:
            continue
        prefix, suffix = line.split(" - ", 1)
        cols, fs = prefix.split(), suffix.split()
        if len(cols) >= 5 and fs and cols[4] == "/sys/fs/cgroup" and fs[0] == "cgroup2":
            return True
    return False


def _self_member(raw):
    if raw is None:
        return None
    return any(line.startswith("0::") for line in raw.splitlines())


def _controllers(raw):
    if raw is None:
        return []
    return sorted(set(raw.split()).intersection(KNOWN_CONTROLLERS))


def _status_fields(raw):
    if raw is None:
        return None, None
    nn = re.search(r"^NoNewPrivs:\s*([01])\s*$", raw, re.MULTILINE)
    sc = re.search(r"^Seccomp:\s*([012])\s*$", raw, re.MULTILINE)
    return ((nn.group(1) == "1") if nn else None,
            int(sc.group(1)) if sc else None)


def _nonzero(raw):
    if raw is None:
        return None
    val = raw.strip()
    if not val.isascii() or not val.isdecimal() or len(val) > 20:
        return None
    return int(val) > 0


def _os_variant(raw):
    if raw is None:
        return None
    entries = {}
    for line in raw.splitlines():
        if line.startswith(("ID=", "VARIANT_ID=")):
            key, val = line.split("=", 1)
            entries[key] = val.strip().strip('"').strip("'").lower()
    if "ID" not in entries:
        return None
    return entries["ID"] == "fedora" and entries.get("VARIANT_ID") == "silverblue"


def _positive_bool(value):
    return value if type(value) is bool else None


def assess(snapshot):
    """Parse a limited untrusted fixture or explicit host read. ALWAYS DENY."""
    valid = (type(snapshot) is dict and set(snapshot) == SNAPSHOT_KEYS
             and type(snapshot.get("sources")) is dict
             and set(snapshot["sources"]) == set(HOST_SOURCES)
             and type(snapshot.get("namespaces")) is dict
             and set(snapshot["namespaces"]) == set(NAMESPACE_KINDS)
             and type(snapshot.get("tools")) is dict
             and set(snapshot["tools"]) == set(TOOLS)
             and type(snapshot.get("userBusSocket")) is bool)
    sources = snapshot["sources"] if valid else {}
    namespaces = snapshot["namespaces"] if valid else {}
    tools = snapshot["tools"] if valid else {}
    corrupt = valid and any(
        raw is not None and _safe_source(raw) is None for raw in sources.values()
    )
    invalid = not valid or corrupt
    def get(key):
        return _safe_source(sources.get(key)) if not invalid else None
    no_new_privs, seccomp = _status_fields(get("status"))
    result = {
        "schema": SCHEMA, "decision": "DENY",
        "inventoryOnly": True, "kernelAttested": False,
        "credentialBoundaryCertified": False, "nativeToolsDisabled": False,
        "networkEgressDenied": False, "cgroupDelegationCertified": False,
        "gatewayStopAuthenticated": False, "descendantTeardownCertified": False,
        "launchAuthorized": False, "modelCalls": 0, "gatewayCalls": 0,
        "toolCalls": 0, "hospitalWrites": 0, "productionReady": False,
        "observations": {
            "fedoraSilverblueReported": _os_variant(get("osRelease")),
            "cgroupV2MountedAtStandardPath": _mount_v2(get("mountinfo")),
            "selfCgroupV2Member": _self_member(get("selfCgroup")),
            "visibleCgroupControllers": _controllers(get("controllers")),
            "currentProcessNoNewPrivs": no_new_privs,
            "currentProcessSeccompMode": seccomp,
            "unprivilegedUsernsSysctlAllows": _nonzero(get("unprivilegedUserns")),
            "maxUserNamespacesPositive": _nonzero(get("maxUserns")),
            "selinuxEnforcing": _nonzero(get("selinuxEnforce")),
            "namespaceLinksPresent": {
                kind: _positive_bool(namespaces.get(kind)) if not invalid else None
                for kind in NAMESPACE_KINDS
            },
            "toolExecutablesPresent": {
                kind: _positive_bool(tools.get(kind)) if not invalid else None
                for kind in TOOLS
            },
            "userBusSocketPresent": (
                _positive_bool(snapshot.get("userBusSocket")) if not invalid else None
            ),
        },
        "reasons": sorted(set(REASONS) | ({"INVALID_INVENTORY_SNAPSHOT"} if invalid else set())),
    }
    return result


def _read_bounded(path):
    """Only call with literal values from HOST_SOURCES; no arbitrary file API."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read(MAX_SOURCE_CHARS + 1)
        return data if len(data) <= MAX_SOURCE_CHARS else None
    except OSError:
        return None


def _fixed_namespace_exists(name):
    path = "/proc/self/ns/" + name  # name from NAMESPACE_KINDS only
    try:
        target = os.readlink(path)
        return re.fullmatch(re.escape(name) + r":\[[0-9]+\]", target) is not None
    except FileNotFoundError:
        return False
    except OSError:
        return None


def _fixed_tool_executable(path):
    try:
        result = os.stat(path)  # fixed literal path from TOOLS
        return stat.S_ISREG(result.st_mode) and bool(result.st_mode & 0o111)
    except FileNotFoundError:
        return False
    except OSError:
        return None


def _fixed_bus_socket():
    try:
        path = "/run/user/" + str(os.getuid()) + "/bus"
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except FileNotFoundError:
        return False
    except OSError:
        return None


def collect_host_readonly():
    """Read only bounded, fixed public OS capability paths after CLI opt-in."""
    if sys.platform != "linux":
        raise RuntimeError("H6_LINUX_REQUIRED")
    return {
        "sources": {key: _read_bounded(path) for key, path in HOST_SOURCES.items()},
        "namespaces": {key: _fixed_namespace_exists(key) for key in NAMESPACE_KINDS},
        "tools": {key: _fixed_tool_executable(path) for key, path in TOOLS.items()},
        "userBusSocket": _fixed_bus_socket(),
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["--host-readonly"]:
        print(json.dumps({
            "schema": SCHEMA, "decision": "DENY",
            "reason": "EXPLICIT_HOST_READONLY_OPT_IN_REQUIRED",
            "hostReads": 0, "modelCalls": 0, "gatewayCalls": 0,
            "launchAuthorized": False, "productionReady": False,
        }, sort_keys=True))
        return 2
    try:
        report = assess(collect_host_readonly())
    except Exception:
        # No exception messages: source and OS details must not leak.
        report = assess(None)
    print(json.dumps(report, sort_keys=True))
    return 0  # Successful inspection is NOT an authorization.


if __name__ == "__main__":
    raise SystemExit(main())
