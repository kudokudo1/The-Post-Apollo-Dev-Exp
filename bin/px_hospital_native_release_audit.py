#!/usr/bin/env python3
"""Hospital Trash + Restore / read-only old-writer collision audit.

Source-only admission evidence. This tool NEVER migrates/backs up/moves a DB,
does not start/stop services, and does not grant authorization. It reads the
root-controlled existing Hospital writer configuration plus Linux process
file-descriptor evidence. No command-line database, owner, or /proc override
is allowed. Even a clean scan is NOT approval: future old-writer launches
must separately be fenced and recovery must be independently accepted.

The inspector intentionally refuses to certify an incomplete /proc scan.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys

CONFIG=Path("/etc/post-apollo/hospital/room-writer.json")
SCHEMA="post-apollo.hospital.protected-room-writer-host.v1"
FIELDS={"schema","writerUid","clientUid","runtimeUid","stateDirectory","socketDirectory"}
DB_NAMES={"hospital.db","hospital.db-wal","hospital.db-shm"}
PROC=Path("/proc")
MAX_PROC=250000

# Source-level pending commands from the separately owned, unmerged
# Session/Doctor/Bed branches. This list is release evidence, NOT a native
# command allowlist and NOT authority to run their SQL. Do not make a
# compatibility claim before each owner contract, permission boundary,
# installed source hash and all-writer cutover have been reviewed.
UNRECONCILED_NATIVE_COMMANDS = frozenset((
    "session-attach-atomic",
    "session-succeed-atomic",
    "room-bed-claim-atomic",
    "room-bed-claim-signed-atomic",
))

class AuditHold(RuntimeError):
    pass

def hold(message):
    raise AuditHold("HOSPITAL_RELEASE_HOLD // "+message)

def _unique(pairs):
    result={}
    for k,v in pairs:
        if k in result:
            hold("DUPLICATE_CONFIG_FIELD")
        result[k]=v
    return result

def _literal_json(raw):
    try:
        return json.loads(raw.decode("utf-8","strict"),
                          object_pairs_hook=_unique,
                          parse_constant=lambda _: hold("NONFINITE_CONFIG"))
    except (UnicodeError,ValueError,TypeError) as exc:
        raise AuditHold("HOSPITAL_RELEASE_HOLD // INVALID_CONFIG") from exc

def _root_controlled_file(path):
    if not isinstance(path,Path) or not path.is_absolute():
        hold("INVALID_TRUST_PATH")
    for parent in path.parents:
        try:
            st=parent.lstat()
        except OSError as exc:
            raise AuditHold("HOSPITAL_RELEASE_HOLD // ROOT_PARENT_UNAVAILABLE") from exc
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid!=0
            or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            hold("ROOT_PARENT_UNTRUSTED")
    fd=None
    try:
        fd=os.open(path,os.O_RDONLY | getattr(os,"O_NOFOLLOW",0)
                   | getattr(os,"O_CLOEXEC",0))
        before=os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid!=0
            or before.st_nlink!=1 or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not 1<=before.st_size<=4096):
            hold("ROOT_CONFIG_UNTRUSTED")
        raw=os.read(fd,4097)
        after=os.fstat(fd)
        if (len(raw)!=before.st_size
            or (before.st_dev,before.st_ino,before.st_size,
                before.st_mtime_ns,before.st_ctime_ns)
            != (after.st_dev,after.st_ino,after.st_size,
                after.st_mtime_ns,after.st_ctime_ns)):
            hold("ROOT_CONFIG_CHANGED")
        return raw
    except OSError as exc:
        raise AuditHold("HOSPITAL_RELEASE_HOLD // CONFIG_NOT_INSTALLED") from exc
    finally:
        if fd is not None:os.close(fd)

def read_installed_config():
    obj=_literal_json(_root_controlled_file(CONFIG))
    if type(obj) is not dict or set(obj)!=FIELDS or obj["schema"]!=SCHEMA:
        hold("UNREVIEWED_HOST_CONFIG")
    uids=(obj["writerUid"],obj["clientUid"],obj["runtimeUid"])
    if (any(type(u) is not int or u<=0 for u in uids)
        or len(set(uids))!=3):
        hold("WRITER_RUNTIME_DESKTOP_UID_COLLISION")
    for key in ("stateDirectory","socketDirectory"):
        value=obj[key]
        if (type(value) is not str or not 1<=len(value)<=256
            or "\x00" in value):
            hold("UNTRUSTED_CONFIG_PATH")
        path=Path(value)
        if not path.is_absolute() or ".." in path.parts:
            hold("CONFIG_PATH_NOT_PINNED")
    if obj["stateDirectory"]==obj["socketDirectory"]:
        hold("DB_AND_SOCKET_DIRECTORIES_COLLIDE")
    return obj

def _read_uid(status):
    try:
        data=status.read_text()
    except (OSError,UnicodeError) as exc:
        raise AuditHold("HOSPITAL_RELEASE_HOLD // PROC_STATUS_UNREADABLE") from exc
    lines=[line.split()[1:] for line in data.splitlines()
           if line.startswith("Uid:")]
    if len(lines)!=1 or len(lines[0])!=4:
        hold("PROC_UID_UNVERIFIABLE")
    try:
        uids=[int(x) for x in lines[0]]
    except ValueError as exc:
        raise AuditHold("HOSPITAL_RELEASE_HOLD // PROC_UID_INVALID") from exc
    if len(set(uids))!=1:
        hold("PROC_UID_TRANSITION")
    return uids[0]

def _fd_flags(path):
    try:
        text=path.read_text()
    except (OSError,UnicodeError) as exc:
        raise AuditHold("HOSPITAL_RELEASE_HOLD // PROC_FD_FLAGS_UNREADABLE") from exc
    match=re.findall(r"^flags:\s+([0-7]+)$",text,re.MULTILINE)
    if len(match)!=1:
        hold("PROC_FD_FLAGS_MISSING")
    return int(match[0],8)

def scan_open_hospital_descriptors(proc_root=PROC):
    """Read-only /proc inspector; overridable only as a library test fixture.

    Each inspected descriptor records its actual file identity and writer UID;
    never reads private Hospital DB bytes or publishes user paths.
    """
    records=[]
    unknown=0
    checked=0
    try:
        processes=list(proc_root.iterdir())
    except OSError as exc:
        raise AuditHold("HOSPITAL_RELEASE_HOLD // PROC_UNAVAILABLE") from exc
    for directory in processes:
        if not directory.name.isdecimal():
            continue
        checked+=1
        if checked>MAX_PROC:
            hold("PROC_BOUNDS_EXCEEDED")
        try:
            handles=list((directory/"fd").iterdir())
            uid=_read_uid(directory/"status")
        except FileNotFoundError:
            # A process may exit while scanning; disappearance does not
            # certify a clean system. A second quiesced scan is required.
            unknown+=1
            continue
        except (OSError,AuditHold):
            unknown+=1
            continue
        for fd in handles:
            if not fd.name.isdecimal():
                continue
            try:
                target=os.readlink(fd)
            except FileNotFoundError:
                unknown+=1
                continue
            except OSError:
                unknown+=1
                continue
            stripped=target.removesuffix(" (deleted)")
            name=Path(stripped).name
            if name not in DB_NAMES:
                continue
            try:
                flags=_fd_flags(directory/"fdinfo"/fd.name)
                st=fd.stat() # follows /proc fd handle; no user bytes read
            except (OSError,AuditHold):
                unknown+=1
                continue
            records.append({
                "pid":int(directory.name),
                "uid":uid,
                "name":name,
                "device":int(st.st_dev),
                "inode":int(st.st_ino),
                "access":flags & os.O_ACCMODE,
                "deleted":target.endswith(" (deleted)"),
                "target":stripped,
            })
    return records,unknown,checked

def assess_writers(config,descriptors,unknown,checked):
    if type(config) is not dict or not set(FIELDS).issubset(config):
        hold("MISSING_PROTECTED_CONFIG")
    if type(unknown) is not int or type(checked) is not int:
        hold("INVALID_PROCESS_EVIDENCE")
    if checked <= 0 or unknown!=0:
        hold("INCOMPLETE_LIVE_PROCESS_INVENTORY")
    approved=str(Path(config["stateDirectory"])/"hospital.db")
    foreign=[]
    for item in descriptors:
        # Any open Hospital database outside the protected owner-only
        # path is evidence of a concurrent old DB, even if read-only.
        # Any process other than dedicated owner touching the protected
        # DB is likewise unapproved; installed provenance still needs
        # an independently verified process/cgroup/executable inventory.
        base=item["target"]
        path=base.removesuffix("-wal").removesuffix("-shm")
        if (path!=approved or item["uid"]!=config["writerUid"]
            or item["deleted"]):
            foreign.append((item["pid"],item["name"]))
    return {
        "schema":"postapollo.hospital.release-writer-audit.v1",
        "observedProcessCount":checked,
        "hospitalOpenDescriptors":len(descriptors),
        "unapprovedHospitalDescriptorCount":len(foreign),
        "oldOrForeignDatabaseObserved":bool(foreign),
        "processInventoryComplete":True,
        "externalWritersStopped":False,
        "oldLaunchPathsFenced":False,
        "verifiedBackupAndRollback":False,
        "nativeApprovalInstalledAndReviewed":False,
        "operatorAcceptedCutover":False,
        "allWriterCompatibilityVerified":False,
        "unreconciledHospitalCommands":sorted(UNRECONCILED_NATIVE_COMMANDS),
        "releaseApproved":False,
    }

def main(argv=None):
    if argv is None:
        argv=sys.argv[1:]
    if argv or sys.platform!="linux" or os.getuid()!=0 or os.geteuid()!=0:
        hold("ROOT_READ_ONLY_AUDIT_ONLY")
    config=read_installed_config()
    records,unknown,checked=scan_open_hospital_descriptors()
    evidence=assess_writers(config,records,unknown,checked)
    # Show only sanitized inventory counts; never disclose actual paths,
    # PIDs, Hospital data or installed private security policy.
    print(json.dumps(evidence,sort_keys=True,separators=(",",":")))
    return 0 if not evidence["oldOrForeignDatabaseObserved"] else 2

if __name__=="__main__":
    try:raise SystemExit(main())
    except (AuditHold,OSError,ValueError,TypeError):
        print("HOSPITAL_RELEASE_HOLD // INCOMPLETE_OR_UNTRUSTED_HOST_EVIDENCE",
              file=sys.stderr)
        raise SystemExit(2)
