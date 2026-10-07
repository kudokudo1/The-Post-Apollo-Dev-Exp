#!/usr/bin/env python3
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "bin" / "px"


def run_px(env, *args, expect=0):
    proc = subprocess.run(
        [str(PX), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != expect:
        raise AssertionError(
            f"px {' '.join(args)} exited {proc.returncode}, expected {expect}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def payload(proc):
    return json.loads(proc.stdout)


def main():
    with tempfile.TemporaryDirectory(prefix="px-operation-test-") as tmp:
        env = os.environ.copy()
        env["PX_OPERATION_DB"] = str(Path(tmp) / "operations.db")

        started = payload(
            run_px(
                env,
                "operation",
                "start",
                "--action-id",
                "test.local",
                "--title",
                "Test Local Mutation",
                "--mutation",
                "local",
                "--recovery",
                "EVIDENCE_ONLY",
                "--command-json",
                '["agent","cancel","session-1","--json"]',
                "--arguments-json",
                '{"session_id":"session-1"}',
                "--before-json",
                '{"armed":false,"preflight":""}',
                "--json",
            )
        )

        operation_id = started["id"]
        assert operation_id.startswith("op-")
        assert started["status"] == "RUNNING"
        assert started["recovery"] == "EVIDENCE_ONLY"
        assert started["command"] == ["agent", "cancel", "session-1", "--json"]
        assert started["arguments"]["session_id"] == "session-1"

        rows = payload(run_px(env, "operations", "--json"))
        assert len(rows) == 1
        assert rows[0]["id"] == operation_id

        inspected = payload(
            run_px(env, "operation", "get", operation_id, "--json")
        )
        assert inspected["status"] == "RUNNING"

        assert started["ownerState"] == "UNKNOWN"

        unknown_reconcile = run_px(
            env,
            "operation",
            "reconcile",
            operation_id,
            "--json",
            expect=1,
        )
        assert "owner state is UNKNOWN" in unknown_reconcile.stderr

        live_started = payload(
            run_px(
                env,
                "operation",
                "start",
                "--action-id",
                "test.live-owner",
                "--mutation",
                "local",
                "--recovery",
                "EVIDENCE_ONLY",
                "--command-json",
                '["true"]',
                "--owner-pid",
                str(os.getpid()),
                "--json",
            )
        )
        live_id = live_started["id"]
        assert live_started["ownerState"] == "LIVE"

        live_reconcile = run_px(
            env,
            "operation",
            "reconcile",
            live_id,
            "--json",
            expect=1,
        )
        assert "owner is still live" in live_reconcile.stderr

        sleeper = subprocess.Popen(["sleep", "30"])
        try:
            stale_started = payload(
                run_px(
                    env,
                    "operation",
                    "start",
                    "--action-id",
                    "test.stale-owner",
                    "--mutation",
                    "remote",
                    "--recovery",
                    "EVIDENCE_ONLY",
                    "--command-json",
                    '["sleep","30"]',
                    "--owner-pid",
                    str(sleeper.pid),
                    "--json",
                )
            )
        finally:
            sleeper.terminate()
            sleeper.wait(timeout=5)

        stale_id = stale_started["id"]
        assert stale_started["ownerState"] == "LIVE"

        stale_rows = payload(
            run_px(
                env,
                "operation",
                "stale",
                "--limit",
                "100",
                "--json",
            )
        )
        assert [row["id"] for row in stale_rows] == [stale_id]
        assert stale_rows[0]["ownerState"] == "STALE"
        assert stale_rows[0]["status"] == "RUNNING"

        reconciled = payload(
            run_px(
                env,
                "operation",
                "reconcile",
                stale_id,
                "--json",
            )
        )
        assert reconciled["status"] == "INTERRUPTED"
        assert reconciled["journalStatus"] == "FAILED"
        assert reconciled["verificationStatus"] == "UNAVAILABLE"
        assert reconciled["interrupted"] is True
        assert reconciled["interruptedAt"]
        assert reconciled["executionOutcome"] == "UNKNOWN"
        assert reconciled["after"]["interruption"]["outcome"] == "UNKNOWN"
        assert reconciled["after"]["interruption"]["ownerState"] == "STALE"
        assert "execution outcome is UNKNOWN" in reconciled["resultSummary"]

        interrupted_rows = payload(
            run_px(
                env,
                "operations",
                "--status",
                "INTERRUPTED",
                "--json",
            )
        )
        assert [row["id"] for row in interrupted_rows] == [stale_id]

        failed_rows = payload(
            run_px(
                env,
                "operations",
                "--status",
                "FAILED",
                "--json",
            )
        )
        assert stale_id not in [row["id"] for row in failed_rows]

        stale_rows_after = payload(
            run_px(env, "operation", "stale", "--json")
        )
        assert stale_id not in [row["id"] for row in stale_rows_after]

        duplicate_reconcile = run_px(
            env,
            "operation",
            "reconcile",
            stale_id,
            "--json",
            expect=1,
        )
        assert "already INTERRUPTED" in duplicate_reconcile.stderr

        recovery = payload(
            run_px(env, "operation", "recovery", operation_id, "--json")
        )
        assert recovery["recovery"] == "EVIDENCE_ONLY"
        assert recovery["automaticRecoveryAvailable"] is False
        assert recovery["strategy"] == "EVIDENCE_ONLY"
        assert "not promised" in recovery["reason"]

        evidence_preflight = payload(
            run_px(
                env,
                "mutation-preflight",
                "px.operation.recover.execute",
                json.dumps({"operation_id": operation_id}),
            )
        )
        assert evidence_preflight["allowed"] is False
        assert evidence_preflight["frozenCommand"] == [
            "operation",
            "recover",
            operation_id,
            "--json",
        ]

        payload(
            run_px(
                env,
                "operation",
                "finish",
                live_id,
                "--status",
                "COMPLETE",
                "--exit-code",
                "0",
                "--verification-status",
                "NOT_RUN",
                "--after-json",
                '{}',
                "--verification-json",
                '{}',
                "--result-summary",
                "live-owner test complete",
                "--json",
            )
        )

        finished = payload(
            run_px(
                env,
                "operation",
                "finish",
                operation_id,
                "--status",
                "COMPLETE",
                "--exit-code",
                "0",
                "--verification-status",
                "PASSED",
                "--after-json",
                '{"stdout":{"ok":true},"stderr":""}',
                "--verification-json",
                '{"status":"POST_OP_CLEAN"}',
                "--result-summary",
                "mutation and verification succeeded",
                "--json",
            )
        )

        assert finished["status"] == "COMPLETE"
        assert finished["exitCode"] == 0
        assert finished["verificationStatus"] == "PASSED"
        assert finished["verification"]["status"] == "POST_OP_CLEAN"
        assert finished["completedAt"]

        complete_rows = payload(
            run_px(
                env,
                "operations",
                "--status",
                "COMPLETE",
                "--limit",
                "10",
                "--json",
            )
        )
        assert [row["id"] for row in complete_rows] == [operation_id]

        duplicate = run_px(
            env,
            "operation",
            "finish",
            operation_id,
            "--status",
            "FAILED",
            "--json",
            expect=1,
        )
        assert "already COMPLETE" in duplicate.stderr

        create_started = payload(
            run_px(
                env,
                "operation",
                "start",
                "--action-id",
                "workflow.create",
                "--title",
                "Create Workflow",
                "--mutation",
                "remote",
                "--recovery",
                "CONTENT_RECOVERABLE",
                "--command-json",
                '["create","owner/repo","smoke","recoverable","manual","--install","--json"]',
                "--arguments-json",
                '{"repository":"dev","template":"smoke","slug":"recoverable"}',
                "--before-json",
                '{"armed":true,"preflight":"CREATE WORKFLOW"}',
                "--json",
            )
        )
        create_id = create_started["id"]
        yaml_text = "name: recoverable\non:\n  workflow_dispatch:\n"
        create_after = {
            "stdout": {
                "repository": "owner/repo",
                "base": "main",
                "path": ".github/workflows/recoverable.yml",
                "yaml": yaml_text,
                "install": {
                    "installed": True,
                    "commit": "c" * 40,
                },
            },
            "stderr": "",
        }
        create_verification = {
            "passed": True,
            "target": {
                "remoteBlobSha": "blob-recoverable",
                "currentBaseSha": "d" * 40,
                "expectedYamlSha": "e" * 64,
            },
        }
        payload(
            run_px(
                env,
                "operation",
                "finish",
                create_id,
                "--status",
                "COMPLETE",
                "--exit-code",
                "0",
                "--verification-status",
                "PASSED",
                "--after-json",
                json.dumps(create_after),
                "--verification-json",
                json.dumps(create_verification),
                "--result-summary",
                "workflow creation verified",
                "--json",
            )
        )

        create_recovery = payload(
            run_px(env, "operation", "recovery", create_id, "--json")
        )
        assert create_recovery["recovery"] == "CONTENT_RECOVERABLE"
        assert create_recovery["automaticRecoveryAvailable"] is False
        assert create_recovery["executorAvailable"] is True
        assert create_recovery["requiresLiveValidation"] is True
        assert create_recovery["planAvailable"] is True
        assert create_recovery["strategy"] == "DELETE_CREATED_WORKFLOW"
        assert create_recovery["plan"]["repository"] == "owner/repo"
        assert create_recovery["plan"]["base"] == "main"
        assert (
            create_recovery["plan"]["path"]
            == ".github/workflows/recoverable.yml"
        )
        assert create_recovery["plan"]["yaml"] == yaml_text
        assert create_recovery["plan"]["remoteBlobSha"] == "blob-recoverable"
        assert create_recovery["executionCommand"] == [
            "operation",
            "recover",
            create_id,
            "--json",
        ]
        assert "requires live history and content validation" in create_recovery["reason"]

        create_preflight = payload(
            run_px(
                env,
                "mutation-preflight",
                "px.operation.recover.execute",
                json.dumps({"operation_id": create_id}),
            )
        )
        assert create_preflight["allowed"] is True
        assert create_preflight["frozenCommand"] == [
            "operation",
            "recover",
            create_id,
            "--json",
        ]
        assert "DELETE_CREATED_WORKFLOW" in create_preflight["summary"]
        token = json.loads(create_preflight["token"])
        assert token["operationId"] == create_id
        assert token["actionId"] == "workflow.create"
        assert token["strategy"] == "DELETE_CREATED_WORKFLOW"
        assert token["repository"] == "owner/repo"
        assert token["base"] == "main"
        assert token["path"] == ".github/workflows/recoverable.yml"
        assert token["blobSha"] == "blob-recoverable"
        assert token["requiresLiveValidation"] is True

        invalid = run_px(
            env,
            "operation",
            "start",
            "--action-id",
            "bad",
            "--mutation",
            "local",
            "--recovery",
            "EVIDENCE_ONLY",
            "--command-json",
            '{}',
            "--json",
            expect=1,
        )
        assert "command must be a JSON list" in invalid.stderr

    with tempfile.TemporaryDirectory(prefix="px-operation-migration-") as tmp:
        legacy_db = Path(tmp) / "legacy.db"
        with sqlite3.connect(legacy_db) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO schema_meta(key, value)
                    VALUES('schema_version', '1');
                CREATE TABLE operations (
                    operation_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    mutation TEXT NOT NULL,
                    recovery TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'RUNNING',
                    command_json TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    before_json TEXT NOT NULL DEFAULT '{}',
                    after_json TEXT NOT NULL DEFAULT '{}',
                    exit_code INTEGER,
                    verification_status TEXT NOT NULL DEFAULT 'NOT_RUN',
                    verification_json TEXT NOT NULL DEFAULT '{}',
                    result_summary TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );
                INSERT INTO operations(
                    operation_id, action_id, mutation, recovery,
                    command_json
                ) VALUES(
                    'legacy-running',
                    'legacy.action',
                    'local',
                    'EVIDENCE_ONLY',
                    '["true"]'
                );
                """
            )

        legacy_env = os.environ.copy()
        legacy_env["PX_OPERATION_DB"] = str(legacy_db)
        legacy_rows = payload(run_px(legacy_env, "operations", "--json"))
        assert legacy_rows[0]["id"] == "legacy-running"
        assert legacy_rows[0]["ownerState"] == "UNKNOWN"

        with sqlite3.connect(legacy_db) as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(operations)").fetchall()
            }
            version = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        assert {
            "owner_pid",
            "owner_boot_id",
            "owner_start_ticks",
            "interrupted_at",
        } <= columns
        assert version == "2"

    print("PX operation journal contract: PASS")


if __name__ == "__main__":
    main()
