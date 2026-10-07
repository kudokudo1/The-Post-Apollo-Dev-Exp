#!/usr/bin/env python3
import json
import os
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

        recovery = payload(
            run_px(env, "operation", "recovery", operation_id, "--json")
        )
        assert recovery["recovery"] == "EVIDENCE_ONLY"
        assert recovery["automaticRecoveryAvailable"] is False
        assert recovery["strategy"] == "EVIDENCE_ONLY"
        assert "not promised" in recovery["reason"]

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

    print("PX operation journal contract: PASS")


if __name__ == "__main__":
    main()
