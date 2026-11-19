"""Fail-closed, owner-process routing for legacy Hospital store commands.

Only the separately authenticated PX *runtime service UID* may invoke this
bridge through ProtectedRoomWriter. An ordinary desktop UID has no access
to store-command, even if it can request signed Room Trash/Restore.

This module executes the existing PX v12 store implementation, preserving
its validators, schema constraints, and Assignment behavior, instead of
duplicating thousands of lines of SQL. It never opens a database, parses
an unbounded stream, shells out, reads client-selected Python code, or
supports SQL/DDL/migration/Room lifecycle mutators through this bridge.

A trusted native installer MUST own the Python source/parent directories,
the PX runtime identity, and the socket ACL before real deployment.
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
from pathlib import Path

_MAX_ARGV = 128
_MAX_ARG_LENGTH = 49152

# Deliberate declaration: a change to the Hospital parser requires a human
# update to the allowlist and source contract. Unknown future Bed/Doctor
# commands must NOT become remotely writable by appearing in argparse.
READ_COMMANDS = frozenset((
    "status", "doctor", "doctors", "room", "rooms", "session", "sessions",
    "events", "assignment-authority", "assignment", "assignments",
    "chart-entry", "chart-entries", "chart-suggestion",
    "chart-suggestions", "room-report", "room-reports", "checkpoints",
    "messages",
))
WRITE_COMMANDS = frozenset((
    "doctor-put", "doctor-name-set", "patient-put", "room-bind",
    "room-put", "room-name-set", "session-put", "session-runtime",
    "event-append", "assignment-create", "assignment-update",
    "assignment-status", "assignment-activate", "chart-entry-add",
    "chart-entry-status", "chart-suggestion-add",
    "chart-suggestion-promote", "chart-suggestion-reject",
    "room-report-append", "checkpoint-append", "message-append",
))
EXCLUDED_COMMANDS = frozenset((
    "init", "room-lifecycle-review", "room-lifecycle-bin",
    "room-lifecycle-trash", "room-lifecycle-restore",
))
if READ_COMMANDS & WRITE_COMMANDS or (
        (READ_COMMANDS | WRITE_COMMANDS) & EXCLUDED_COMMANDS):
    raise RuntimeError("HOSPITAL_ROUTE_POLICY_COLLISION")


class StoreCommandHold(RuntimeError):
    pass


def _legacy_source():
    # The service manager must verify a root-controlled installed release.
    # Never obtain module paths or names from RPC, environment or caller UID.
    path = Path(__file__).resolve().with_name("px-hospital-store")
    loader = importlib.machinery.SourceFileLoader(
        "_px_hospital_protected_store_source", str(path),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise StoreCommandHold("STORE_SOURCE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# Load once from the same supervised release as the protected writer.
_store = _legacy_source()


def declared_commands():
    parser = _store.build_parser()
    commands = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            commands.update(action.choices)
    return frozenset(commands)


def route_coverage():
    """Fail CI when a new command is not assigned a reviewed authority lane."""
    return declared_commands() == (
        READ_COMMANDS | WRITE_COMMANDS | EXCLUDED_COMMANDS
    )


def parse_argv(argv):
    if (type(argv) is not list or not 1 <= len(argv) <= _MAX_ARGV
            or type(argv[0]) is not str or not argv[0]
            or any(type(arg) is not str
                   or len(arg) > _MAX_ARG_LENGTH or "\x00" in arg
                   for arg in argv)):
        raise StoreCommandHold("INVALID_BOUNDED_ARGUMENTS")
    # Preserve original CLI reset semantics such as --name "" on
    # Doctor/Room display names; only the command token must be nonempty.
    command = argv[0]
    if command not in READ_COMMANDS | WRITE_COMMANDS:
        raise StoreCommandHold("COMMAND_NOT_EXPOSED")
    # Never let an RPC read arbitrary server stdin or replace the source DB.
    if any(arg in ("--body-stdin", "--signed-authorization-file")
           for arg in argv[1:]):
        raise StoreCommandHold("FILE_AND_STDIN_ROUTING_DENIED")
    if not route_coverage():
        raise StoreCommandHold("SOURCE_COMMAND_CONTRACT_CHANGED")
    try:
        args = _store.build_parser().parse_args(argv + ["--json"])
    except SystemExit as exc:
        raise StoreCommandHold("COMMAND_ARGUMENTS_REFUSED") from exc
    if args.command != command or getattr(args, "body_stdin", False):
        raise StoreCommandHold("COMMAND_PARSER_MISMATCH")
    return args


def _require_authority(db, args):
    result = _store.assignment_authority(
        db, args.room_id, args.team, args.repository, args.permission,
    )
    if args.require and not result["allowed"]:
        raise StoreCommandHold("ASSIGNMENT_AUTHORITY_REFUSED")
    return result


# Each route calls the ORIGINAL PX-owned store function, preserving its
# validation and existing SQL. No raw SQL string is ever caller-supplied.
READ_ROUTES = {
    "status": lambda db, a: _store.database_status(db),
    "doctor": lambda db, a: _store.doctor_record(db, a.doctor_id),
    "doctors": lambda db, a: _store.doctors_list(db, a.status or None),
    "room": lambda db, a: _store.room_record(db, a.room_id),
    "rooms": lambda db, a: _store.rooms_list(db),
    "session": lambda db, a: _store.session_record(db, a.session_id),
    "sessions": lambda db, a: _store.sessions_list(db, a.room_id or None),
    "events": lambda db, a: _store.events_list(
        db, a.session_id, a.limit, a.before_id),
    "assignment-authority": _require_authority,
    "assignment": lambda db, a: _store.assignment_record(db, a.assignment_id),
    "assignments": lambda db, a: _store.assignments_list(db, a),
    "chart-entry": lambda db, a: _store.chart_entry_record(db, a.entry_id),
    "chart-entries": lambda db, a: _store.chart_entries_list(db, a),
    "chart-suggestion": lambda db, a: _store.chart_suggestion_record(
        db, a.suggestion_id),
    "chart-suggestions": lambda db, a: _store.chart_suggestions_list(db, a),
    "room-report": lambda db, a: _store.room_report_record(db, a.report_id),
    "room-reports": lambda db, a: _store.room_reports_list(
        db, a.room_id, a.limit, a.before_id, a.report_kind),
    "checkpoints": lambda db, a: _store.checkpoints_list(
        db, a.room_id, a.limit, a.before_id),
    "messages": lambda db, a: _store.messages_list(
        db, a.room_id, a.limit, a.before_id),
}
WRITE_ROUTES = {
    "doctor-put": _store.doctor_put,
    "doctor-name-set": _store.doctor_name_set,
    "patient-put": _store.patient_put,
    "room-bind": _store.room_bind,
    "room-put": _store.room_put,
    "room-name-set": _store.room_name_set,
    "session-put": _store.session_put,
    "session-runtime": _store.session_runtime_update,
    "event-append": _store.event_append,
    "assignment-create": _store.assignment_create,
    "assignment-update": _store.assignment_update,
    "assignment-status": _store.assignment_status,
    "assignment-activate": _store.assignment_activate,
    "chart-entry-add": _store.chart_entry_add,
    "chart-entry-status": _store.chart_entry_status,
    "chart-suggestion-add": _store.chart_suggestion_add,
    "chart-suggestion-promote": _store.chart_suggestion_promote,
    "chart-suggestion-reject": _store.chart_suggestion_reject,
    "room-report-append": _store.room_report_append,
    "checkpoint-append": _store.checkpoint_append,
    "message-append": _store.message_append,
}
if set(READ_ROUTES) != READ_COMMANDS or set(WRITE_ROUTES) != WRITE_COMMANDS:
    raise RuntimeError("HOSPITAL_ROUTE_DISPATCH_INCOMPLETE")


def execute(db, argv):
    """Run one validated, explicitly routed store command on owner DB.

    Caller authorization must be established at the Unix socket first.
    The root-config-pinned PX runtime UID is the only role allowed here.
    """
    args = parse_argv(argv)
    routes = READ_ROUTES if args.command in READ_COMMANDS else WRITE_ROUTES
    return routes[args.command](db, args)
