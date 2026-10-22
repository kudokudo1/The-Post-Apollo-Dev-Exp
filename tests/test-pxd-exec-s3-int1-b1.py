#!/usr/bin/env python3
"""INT1-B1 security proof ONLY: distinct-process atomic fake Hospital storage.

All Hospital reads and writes run inside accepted disposable INT1-P1 Bubblewrap.
No Doctor broker, native provider, real credentials, installed Fedora or live DB.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from px_int1_fixture import DisposablePX

REPO=Path(__file__).resolve().parents[1]
CONTEXT_HASH=hashlib.sha256(b"synthetic continuity").hexdigest()
ROOM="B1-ROOM"
SESSION="b1-session"

class INT1B1AtomicStorageTests(unittest.TestCase):
    def setUp(self):
        self.fx=DisposablePX(REPO)
        self.addCleanup(self.fx.close)
        self.registry=self.fx.root/"providers/fake.json"
        self.registry.write_text(json.dumps({"version":1,"providers":{
            "int1-fake":{"name":"INT1 FAKE",
                         "executionProfile":"EXEC_S3_FAKE_ONLY",
                         "dialect":"exec-s3-fake-only"}
        }}))
        self.registry.chmod(0o600)
        self.assertTrue(self.fx.assert_safe_environment())
        self.ok(self.fx.hospital("init"))
        self.ok(self.fx.hospital(
            "room-bind",ROOM,"--repository","kudokudo1/taskbars-post-apollo",
            "--patient-id","B1-PATIENT","--team","B1-TEAM",
            "--branch","b1-branch","--bed-path","/fixture/bed",
            "--doctor-id","B1-DOCTOR",
        ))
        self.ok(self.fx.hospital(
            "session-put",SESSION,"--room-id",ROOM,
            "--doctor-id","B1-DOCTOR","--provider-id","int1-fake",
            "--status","IDLE",
        ))
        self.ok(self.fx.hospital(
            "session-runtime",SESSION,"--working-directory","/fixture/bed",
            "--status","IDLE",
        ))
        assignment=self.ok(self.fx.hospital(
            "assignment-create","--room-id",ROOM,
            "--title","Synthetic B1 Assignment","--goal","Fake-only test",
            "--permissions-json",'["READ","EDIT"]',
        ))
        self.assignment_id=assignment["id"]
        self.ok(self.fx.hospital("assignment-activate",str(self.assignment_id)))
        self.bootstrap()
        # INT1-B3: a detached B1 accept is now conditional on the complete
        # B2 manifest. The baseline B1 transaction tests use the accepted
        # global, disposable B2 installation with generation 2.
        hooks=self.ok(self.fx.run(
            "/usr/bin/python3", "-B", "/source/bin/px_int1_fake_epoch.py",
            "install", "--room-id", ROOM, "--session-id", SESSION,
            timeout=30,
        ))
        self.assertEqual(hooks["hookCount"],12)
        self.assertEqual(hooks["generation"],2)
        continuity=self.ok(self.fx.run(
            "/usr/bin/python3","-B","/source/bin/px_int1_fake_continuity.py",
            "install","--room-id",ROOM,"--session-id",SESSION,timeout=30,
        ))
        self.assertEqual(continuity["hookCount"],6)
        self.assertEqual(continuity["generation"],3)
        self.generation=3
        self.context_hash=self.ok(self.command(
            "context-digest","--room-id",ROOM,"--session-id",SESSION
        ))["contextHash"]

    def ok(self,result):
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def command(self, *args, input=None):
        return self.fx.run(
            "/usr/bin/python3","-B","/source/bin/px_int1_fake_atomic.py",
            *args, input=input, timeout=30
        )

    def bootstrap(self):
        return self.ok(self.command(
            "bootstrap","--room-id",ROOM,"--session-id",SESSION
        ))

    def snapshot(self):
        return self.ok(self.command(
            "snapshot","--room-id",ROOM,"--session-id",SESSION
        ))

    def accept(self,turn="turn-1",generation=None,body="synthetic only",
               context_hash=None,fail_after=""):
        if generation is None:
            generation=self.generation
        if context_hash is None:
            context_hash=self.context_hash
        args=[
            "accept","--room-id",ROOM,"--session-id",SESSION,
            "--turn-id",turn,"--generation",str(generation),
            "--context-hash",context_hash,"--body-stdin",
        ]
        if fail_after:
            args+=["--fail-after",fail_after]
        return self.command(*args,input=body)

    def state(self):
        return (
            self.ok(self.fx.hospital("messages",ROOM,"--limit","100")),
            self.ok(self.fx.hospital("events",SESSION,"--limit","100")),
        )

    def test_atomic_three_rows_and_cross_process_idempotent_retry(self):
        self.assertEqual(self.snapshot()["generation"],3)
        before=self.state()
        result=self.ok(self.accept())
        self.assertFalse(result["replayed"])
        self.assertEqual(result["state"],"ACCEPTED_UNDISPATCHED")
        after=self.state()
        self.assertEqual(len(after[0])-len(before[0]),1)
        self.assertEqual(len(after[1])-len(before[1]),2)
        self.assertEqual({x["type"] for x in after[1]},{"turn.started","turn.context"})
        repeat=self.ok(self.accept())
        self.assertTrue(repeat["replayed"])
        self.assertEqual(repeat["messageId"],result["messageId"])
        self.assertEqual(after,self.state(),"no duplicate message or event on retry")

    def test_transaction_injections_roll_back_message_and_both_events(self):
        for stage in ("message","context","started"):
            with self.subTest(stage=stage):
                before=self.state()
                refused=self.accept(turn="failed-"+stage,fail_after=stage)
                self.assertNotEqual(refused.returncode,0)
                self.assertIn("TEST INJECT",refused.stderr)
                self.assertEqual(self.state(),before,"partial commit after "+stage)
        good=self.ok(self.accept(turn="clean-after-fault"))
        self.assertEqual(good["state"],"ACCEPTED_UNDISPATCHED")

    def test_request_conflict_refused_without_mutation(self):
        self.ok(self.accept(turn="same-ID"))
        prior=self.state()
        bad=self.accept(turn="same-ID",body="different fake payload")
        self.assertNotEqual(bad.returncode,0)
        self.assertIn("turn ID payload conflict",bad.stderr)
        self.assertEqual(prior,self.state())

    def test_cross_process_revoke_durable_and_stale_generation_denied(self):
        generation=self.snapshot()["generation"]
        prior=self.state()
        revoked=self.ok(self.command(
            "revoke","--room-id",ROOM,"--reason","synthetic pause"
        ))
        self.assertEqual(revoked["generation"],generation+1)
        self.assertTrue(revoked["revoked"])
        # Each command is an INDEPENDENT bwrap/Python process; DB state
        # must persist outside any process-local RLock.
        refused=self.accept(turn="after-revoke",generation=generation)
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("stale or revoked authority",refused.stderr)
        second=self.command(
            "snapshot","--room-id",ROOM,"--session-id",SESSION
        )
        self.assertNotEqual(second.returncode,0)
        self.assertIn("authority revoked",second.stderr)
        self.assertEqual(self.state(),prior)

    def test_revoked_authority_cannot_be_resurrected_by_bootstrap(self):
        self.ok(self.command("revoke","--room-id",ROOM,"--reason","revoked"))
        second=self.command("bootstrap","--room-id",ROOM,"--session-id",SESSION)
        self.assertNotEqual(second.returncode,0)
        self.assertIn("authority revoked",second.stderr)

    def test_revalidate_doctor_and_assignment_inside_transaction(self):
        self.ok(self.fx.hospital(
            "session-put",SESSION,"--room-id",ROOM,
            "--doctor-id","FOREIGN","--provider-id","int1-fake","--status","IDLE"
        ))
        prior=self.state()
        bad=self.accept(turn="foreign")
        self.assertNotEqual(bad.returncode,0)
        self.assertIn("Doctor-to-Room mismatch",bad.stderr)
        self.assertEqual(self.state(),prior)
        self.ok(self.fx.hospital(
            "session-put",SESSION,"--room-id",ROOM,
            "--doctor-id","B1-DOCTOR","--provider-id","int1-fake","--status","IDLE"
        ))
        self.ok(self.fx.hospital(
            "assignment-status",str(self.assignment_id),"PAUSED"
        ))
        before=self.state()
        bad=self.accept(turn="paused")
        self.assertNotEqual(bad.returncode,0)
        self.assertIn("active Room Assignment required",bad.stderr)
        self.assertEqual(self.state(),before)

    def test_b1_i1_matching_whitespace_doctors_refuse_without_any_acceptance(self):
        """Invalid Doctor IDs from genuine synthetic Hospital store must refuse."""
        for invalid in ("   ", " \t "):
            with self.subTest(invalid=repr(invalid)):
                room = self.ok(self.fx.hospital(
                    "room-put", ROOM,
                    "--patient-id", "B1-PATIENT", "--team", "B1-TEAM",
                    "--branch", "b1-branch", "--bed-path", "/fixture/bed",
                    "--doctor-id", invalid, "--provider-id", "int1-fake",
                ))
                session = self.ok(self.fx.hospital(
                    "session-put", SESSION, "--room-id", ROOM,
                    "--doctor-id", invalid, "--provider-id", "int1-fake",
                    "--status", "IDLE",
                ))
                self.assertEqual(room["doctorId"], invalid)
                self.assertEqual(session["doctorId"], invalid)
                self.assertEqual(session["doctorId"], room["doctorId"],
                                 "matching whitespace was permitted in persisted store")
                before = self.state()
                session_before = self.ok(self.fx.hospital("session", SESSION))
                accepted_before = self.accepted_turn_count()
                refused = self.accept(turn="whitespace-" + str(len(invalid)))
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn("Doctor-to-Room mismatch", refused.stderr)
                self.assertEqual(self.state(), before,
                                 "whitespace Doctor must not persist message/events")
                self.assertEqual(self.ok(self.fx.hospital("session", SESSION)),
                                 session_before, "session runtime must stay unchanged")
                self.assertEqual(self.accepted_turn_count(), accepted_before,
                                 "invalid Doctor must not create accepted-turn row")
                self.assertEqual(accepted_before, 0)

    def accepted_turn_count(self):
        # Probe the synthetic acceptance record in an independently spawned,
        # read-only SQLite connection INSIDE the same confined mount namespace.
        probe = self.fx.run(
            "/usr/bin/python3", "-B", "-c",
            "import json,sqlite3; "
            "db=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',"
            "uri=True); "
            "print(json.dumps(db.execute("
            "'SELECT COUNT(*) FROM int1_fake_accepted_turns').fetchone()[0]))"
        )
        return self.ok(probe)

    def test_two_distinct_subprocesses_same_turn_are_single_commit(self):
        def competing(_):
            return self.ok(self.accept(turn="contended"))
        with ThreadPoolExecutor(max_workers=2) as executor:
            a,b=list(executor.map(competing,range(2)))
        self.assertEqual({a["replayed"],b["replayed"]},{True,False})
        self.assertEqual(a["messageId"],b["messageId"])
        messages,events=self.state()
        self.assertEqual(len(messages),1)
        self.assertEqual(len(events),2)

    def test_command_bearing_registry_fails_before_storage_open(self):
        malicious=json.loads(self.registry.read_text())
        malicious["providers"]["int1-fake"]["command"]="/usr/bin/true"
        self.registry.write_text(json.dumps(malicious))
        self.registry.chmod(0o600)
        before=self.state()
        refused=self.command(
            "snapshot","--room-id",ROOM,"--session-id",SESSION
        )
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("unsupported synthetic-only provider",refused.stderr)
        self.assertEqual(self.state(),before)

    def tamper_hooks(self, sql):
        # Independent OS process, confined to the same disposable fixture DB.
        script = (
            "import json,sqlite3; "
            "db=sqlite3.connect("
            "'file:/fixture/hospital/data/hospital.db?mode=rw',uri=True);"
            "db.executescript(" + repr(sql) + ");"
            "print(json.dumps(True))"
        )
        self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", script))

    def test_b3_missing_entire_trigger_manifest_refuses_without_any_writes(self):
        before=self.state()
        self.assertEqual(self.accepted_turn_count(),0)
        self.tamper_hooks("""
        DROP TRIGGER int1_b2_rooms_insert_v1;
        DROP TRIGGER int1_b2_rooms_update_v1;
        DROP TRIGGER int1_b2_rooms_delete_v1;
        DROP TRIGGER int1_b2_sessions_insert_v1;
        DROP TRIGGER int1_b2_sessions_update_v1;
        DROP TRIGGER int1_b2_sessions_delete_v1;
        DROP TRIGGER int1_b2_assignments_insert_v1;
        DROP TRIGGER int1_b2_assignments_update_v1;
        DROP TRIGGER int1_b2_assignments_delete_v1;
        DROP TRIGGER int1_b2_doctors_insert_v1;
        DROP TRIGGER int1_b2_doctors_update_v1;
        DROP TRIGGER int1_b2_doctors_delete_v1;
        """)
        refused=self.accept(turn="no-hooks")
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("incomplete or unexpected hook set",refused.stderr)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.accepted_turn_count(),0)

    def test_b3_missing_one_hook_refuses_new_and_idempotent_replay(self):
        accepted=self.ok(self.accept(turn="already-accepted"))
        self.assertFalse(accepted["replayed"])
        before=self.state()
        count=self.accepted_turn_count()
        self.tamper_hooks("DROP TRIGGER int1_b2_rooms_update_v1;")
        for turn in ("another-turn","already-accepted"):
            with self.subTest(turn=turn):
                refused=self.accept(turn=turn)
                self.assertNotEqual(refused.returncode,0)
                self.assertIn("incomplete or unexpected hook set",refused.stderr)
                self.assertEqual(self.state(),before)
                self.assertEqual(self.accepted_turn_count(),count)

    def test_b3_modified_same_name_trigger_refuses_without_mutation(self):
        before=self.state()
        self.tamper_hooks("""
        DROP TRIGGER int1_b2_rooms_update_v1;
        CREATE TRIGGER int1_b2_rooms_update_v1
        AFTER UPDATE ON rooms BEGIN SELECT 1; END;
        """)
        refused=self.accept(turn="tampered-definition")
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("changed authority trigger definition",refused.stderr)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.accepted_turn_count(),0)

    def test_b3_unexpected_extra_hook_refuses_without_mutation(self):
        before=self.state()
        self.tamper_hooks("""
        CREATE TRIGGER int1_b2_surprise_extra
        AFTER UPDATE ON rooms BEGIN SELECT 1; END;
        """)
        refused=self.accept(turn="extra-hook")
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("incomplete or unexpected hook set",refused.stderr)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.accepted_turn_count(),0)

    def test_b3_independent_hospital_change_and_restore_revokes_old_grant(self):
        before=self.state()
        original=self.snapshot()["generation"]
        self.assertEqual(original,3)
        for doctor in ("B1-OTHER-DOCTOR","B1-DOCTOR"):
            self.ok(self.fx.hospital(
                "room-put",ROOM,"--patient-id","B1-PATIENT",
                "--team","B1-TEAM","--branch","b1-branch",
                "--bed-path","/fixture/bed","--doctor-id",doctor,
                "--provider-id","int1-fake",
            ))
        # B2 must invalidate the B1 grant, even though the Doctor returns.
        self.assertEqual(self.ok(self.fx.hospital("room",ROOM))["doctorId"],
                         "B1-DOCTOR")
        refused=self.accept(turn="stale-after-restore",generation=original)
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("stale or revoked authority",refused.stderr)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.accepted_turn_count(),0)

    def test_host_forged_env_cannot_open_sqlite_via_atomic_cli(self):
        # The source-owned guard executes before sqlite3.connect. This
        # host-process unit test does not access a real DB or provider.
        import importlib.util
        import sys
        guard_spec=importlib.util.spec_from_file_location(
            "px_int1_fake_guard",REPO/"bin/px_int1_fake_guard.py"
        )
        guard=importlib.util.module_from_spec(guard_spec)
        guard_spec.loader.exec_module(guard)
        previous=sys.modules.get("px_int1_fake_guard")
        sys.modules["px_int1_fake_guard"]=guard
        try:
            spec=importlib.util.spec_from_file_location(
                "px_int1_fake_atomic",REPO/"bin/px_int1_fake_atomic.py"
            )
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            env={**guard.ENV_PATHS,**guard.ENV_STATIC,"PWD":"/fixture"}
            with patch.dict(os.environ,env,clear=True):
                with patch.object(module.sqlite3,"connect",side_effect=AssertionError("opened host SQLite")):
                    with self.assertRaisesRegex(RuntimeError,"OS fixture boundary absent"):
                        module.connect()
        finally:
            if previous is None:
                sys.modules.pop("px_int1_fake_guard",None)
            else:
                sys.modules["px_int1_fake_guard"]=previous

if __name__=="__main__":
    unittest.main(verbosity=2)
