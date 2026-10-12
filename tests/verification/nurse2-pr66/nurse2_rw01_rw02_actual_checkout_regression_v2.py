#!/usr/bin/env python3
"""Nurse 2: STRICT read-only actual-source Patient Chart succession acceptance.

Usage:
  python3 nurse2_rw01_rw02_actual_checkout_regression.py /path/to/PX-checkout -v

Imports ACTUAL bin/px-agent and bin/px-hospital-store from the supplied checkout.
Uses only sqlite3 :memory: fixtures and mocked PX store calls. No provider, Git,
network, live Hospital database, repository writes, or installation.

EXPECT on the accepted S3 / combined PR #65 baseline: the RW-01, RW-02 and
unbounded saturation tests FAIL. This is an acceptance gate, NOT a regression
suite that reports known unsafe behavior as success. PXD can use it as a
candidate verification target after fixing Patient-level continuity.
"""
import importlib.machinery
import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


def load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


class PatientSuccessionActualSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = cls.checkout.resolve()
        if not (cls.root / 'bin/px-agent').is_file():
            raise RuntimeError('PX checkout must contain bin/px-agent')
        if not (cls.root / 'bin/px-hospital-store').is_file():
            raise RuntimeError('PX checkout must contain bin/px-hospital-store')
        sys.path.insert(0, str(cls.root / 'bin'))
        cls.store = load('n2_rw_store_actual', cls.root / 'bin/px-hospital-store')
        cls.agent = load('n2_rw_agent_actual', cls.root / 'bin/px-agent')
        cls.fixture = load('n2_rw_fixture_actual',
                           cls.root / 'tests/test-pxd-p1-assignment-integrity.py')

    def setUp(self):
        self.db, assignment_ids = self.fixture.fixture(self.store)
        self.fixture.set_link(self.db, assignment_ids[0])  # ACTIVE Room A, Patient P
        self._old_hospital = self.agent.px_hospital
        self._old_git = self.agent.collect_git_report_evidence
        self._old_retrieve = self.agent.select_relevant_room_history
        self.agent.px_hospital = self.hospital
        self.agent.collect_git_report_evidence = lambda *args: {'status': 'UNAVAILABLE'}
        self.addCleanup(self.restore_agent)
        self.addCleanup(self.db.close)

    def restore_agent(self):
        self.agent.px_hospital = self._old_hospital
        self.agent.collect_git_report_evidence = self._old_git
        self.agent.select_relevant_room_history = self._old_retrieve

    @staticmethod
    def flag(args, name, default=''):
        return args[args.index(name)+1] if name in args else default

    def hospital(self, command, *args):
        s = self.store
        f = self.flag
        if command == 'session':
            return s.session_record(self.db, args[0])
        if command == 'room':
            return s.room_record(self.db, args[0])
        if command == 'assignment':
            return s.assignment_record(self.db, int(args[0]))
        if command == 'chart-entries':
            request = SimpleNamespace(
                scope=f(args, '--scope'), patient_id=f(args, '--patient-id'),
                room_id=f(args, '--room-id'), entry_kind=f(args, '--entry-kind'),
                author_role=f(args, '--author-role'), status=f(args, '--status', 'ACTIVE'),
                limit=int(f(args, '--limit', '100')))
            return s.chart_entries_list(self.db, request)
        if command == 'room-reports':
            return s.room_reports_list(self.db, args[0],
                int(f(args, '--limit', '50')), None, f(args, '--report-kind'))
        if command in ('messages', 'checkpoints', 'chart-suggestions'):
            return []
        raise AssertionError('unhandled PX Hospital command: ' + command)

    def add_patient(self, patient='P', title='', body='', priority=1,
                    kind='DECISION', author='operator', status='ACTIVE'):
        row = self.db.execute('''INSERT INTO chart_entries(
            scope_type,patient_id,entry_kind,title,body_md,priority,status,author_role)
            VALUES ('PATIENT',?,?,?,?,?,?,?)''',
            (patient,kind,title,body,priority,status,author))
        self.db.commit()
        return str(row.lastrowid)

    def add_room(self, room='A', title='', body='', priority=1,
                 kind='DECISION', author='operator'):
        row = self.db.execute('''INSERT INTO chart_entries(
            scope_type,room_id,entry_kind,title,body_md,priority,status,author_role)
            VALUES ('ROOM',?,?,?,?,?,'ACTIVE',?)''',
            (room,kind,title,body,priority,author))
        self.db.commit()
        return str(row.lastrowid)

    def create_patient_q(self):
        self.db.execute('''INSERT INTO patients(patient_id,repository,label)
                        VALUES('Q','another/repo','Other patient')''')
        self.db.execute('''INSERT INTO rooms(room_id,patient_id,team,branch,bed_path,
                    doctor_id,current_assignment_id) VALUES ('C','Q','team-c',
                    'feature/c','/tmp/fakebed-C','doctor-c','')''')
        self.db.execute('''INSERT INTO sessions(session_id,room_id,doctor_id,provider_id)
                    VALUES ('fresh-doctor-Q','C','doctor-Q','mock')''')
        self.db.commit()

    def context_and_prompt(self, session='fresh-doctor-B'):
        ctx = self.agent.live_context_payload(session, query_text='continue assigned work')
        return ctx, self.agent.render_live_context(ctx)

    @staticmethod
    def assert_delivered_or_refused(testcase, operation, required_markers):
        try:
            _, rendered = operation()
        except RuntimeError as exc:
            text = str(exc).upper()
            testcase.assertIn('REFUSED', text, 'Must explicitly refuse, not silently truncate')
            testcase.assertTrue('PATIENT' in text or 'CONTINUITY' in text,
                                'Refusal must identify Patient/continuity scope')
            return
        for marker in required_markers:
            testcase.assertIn(marker, rendered,
                              'Mandatory patient decision cannot silently disappear')

    def test_rw01_low_priority_active_patient_decision_not_displaced(self):
        marker = 'RW01_APPROVED_PATIENT_DECISION_MUST_SURVIVE'
        self.add_patient(title='Historical operator decision', body=marker)
        for n in range(6):
            self.add_patient(title=f'Newer high-priority note {n}',
                             body=f'routine patient context {n}', priority=95,
                             kind='NOTE')
        self.assert_delivered_or_refused(self, self.context_and_prompt, [marker])

    def test_rw02_active_patient_decision_body_not_silently_clipped(self):
        marker = 'RW02_VERIFICATION_REQUIRED_AFTER_LONG_BODY'
        body = 'Intro and context.\n' + ('R' * 1020) + '\n' + marker
        self.add_patient(title='Full-length operator requirement', body=body,
                         priority=100)
        self.assert_delivered_or_refused(
            self, self.context_and_prompt, [marker, 'R' * 1020])

    def test_rw03_excess_patient_required_content_delivered_or_explicitly_refused(self):
        markers = []
        for n in range(28):
            marker = f'RW03_PATIENT_REQUIRED_ITEM_{n:02d}_END'
            markers.append(marker)
            self.add_patient(title=f'Operator requirement {n}',
                             body=('Patient-wide invariant. ' * 6) + marker,
                             priority=95-n, kind='DECISION')
        self.assert_delivered_or_refused(self, self.context_and_prompt, markers)

    def test_rw04_other_patient_context_cannot_receive_patient_p_decisions(self):
        self.create_patient_q()
        p_marker = 'PATIENT_P_ONLY_PRIVATE_REQUIREMENT'
        q_marker = 'PATIENT_Q_ONLY_PRIVATE_REQUIREMENT'
        self.add_patient(patient='P',title='Patient P decision',body=p_marker,priority=95)
        self.add_patient(patient='Q',title='Patient Q decision',body=q_marker,priority=95)
        a, a_prompt = self.context_and_prompt('fresh-doctor-B')
        c, c_prompt = self.context_and_prompt('fresh-doctor-Q')
        self.assertEqual(a['room']['patientId'], 'P')
        self.assertEqual(c['room']['patientId'], 'Q')
        self.assertIn(p_marker, a_prompt)
        self.assertNotIn(q_marker, a_prompt)
        self.assertIn(q_marker, c_prompt)
        self.assertNotIn(p_marker, c_prompt)

    def test_rw05_same_patient_other_room_shares_patient_not_room_context(self):
        marker = 'APPROVED_PATIENT_WIDE_DECISION'
        room_only = 'ROOM_A_ONLY_PROTECTED_DECISION'
        self.add_patient(body=marker, title='Cross-room patient policy', priority=90)
        self.add_room('A', title='Room A only',body=room_only,priority=90)
        self.db.execute('''INSERT INTO sessions(session_id,room_id,doctor_id,provider_id)
                    VALUES ('fresh-doctor-room-B','B','doctor-room-B','mock')''')
        self.db.commit()
        ctx, rendered = self.context_and_prompt('fresh-doctor-room-B')
        self.assertEqual(ctx['room']['patientId'], 'P')
        self.assertIn(marker, rendered)
        self.assertNotIn(room_only, rendered)
        self.assertEqual(ctx['authority']['allowed'], ['READ'])

    def test_rw06_wrong_patient_store_response_must_not_leak_into_prompt(self):
        self.create_patient_q()
        forbidden = 'TAMPERED_FOREIGN_PATIENT_PAYLOAD_NOT_FOR_DOCTOR_B'
        orig = self.agent.px_hospital
        def tampered(command, *args):
            if command == 'chart-entries' and '--scope' in args and \
                    self.flag(args, '--scope').upper() == 'PATIENT':
                return [{'id':'991','scope':'PATIENT','patientId':'Q',
                         'roomId':'','kind':'DECISION','status':'ACTIVE',
                         'authorRole':'operator','title':'Other patient',
                         'body':forbidden,'priority':99}]
            return orig(command, *args)
        self.agent.px_hospital = tampered
        try:
            _, rendered = self.context_and_prompt()
        except RuntimeError as exc:
            self.assertTrue('PATIENT' in str(exc).upper() or
                            'CONTINUITY' in str(exc).upper(),str(exc))
        else:
            self.assertNotIn(forbidden, rendered,
                             'Returned foreign Patient record reached provider prompt')

    def test_rw07_existing_s2_room_handoff_positive_control(self):
        handoff_text = 'HISTORICAL_ROOM_HANDOFF_POSITIVE_CONTROL'
        cur = self.db.execute('''INSERT INTO room_reports(room_id,report_kind,title,body_md)
                                VALUES('A',' hAnDoFf ','Older handoff',?)''',(handoff_text,))
        for n in range(35):
            self.db.execute('''INSERT INTO room_reports(room_id,report_kind,title,body_md)
                               VALUES ('A','DOCTOR_NOTE',?,?)''',
                               (f'Later note {n}', f'ordinary note {n}'))
        self.db.commit()
        ctx, rendered = self.context_and_prompt()
        self.assertIn(str(cur.lastrowid), [row['id'] for row in ctx['requiredHandoffs']])
        self.assertIn(handoff_text, rendered)


    def test_rw08_oversized_patient_decision_refuses_before_provider_dispatch(self):
        """A pathological required decision must refuse without an outgoing turn.

        Uses a disposable Git Bed and intercepts the outgoing message boundary.
        Real provider launch, live DB writes and installed PX are impossible here.
        """
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix='nurse2-rw-boundary-') as temp:
            bed = Path(temp) / 'bed'
            bed.mkdir()
            def git(*argv):
                subprocess.run(['git','-C',str(bed),*argv], check=True,
                               capture_output=True, timeout=10)
            git('init','-q')
            git('config','user.name','Hospital test')
            git('config','user.email','hospital@example.invalid')
            (bed / 'tracked.txt').write_text('baseline\n')
            git('add','tracked.txt')
            git('commit','-qm','baseline')
            git('checkout','-qb','feature/a')
            git('remote','add','origin','https://github.com/test/repo.git')
            self.db.execute("UPDATE rooms SET bed_path=?, branch='feature/a' WHERE room_id='A'",(str(bed),))
            self.db.commit()
            self.add_patient(title='Oversized mandatory patient decision', priority=99,
                             body=('Require further approval. ' * 3200) +
                                  'RW08_ESSENTIAL_END_OF_DECISION')
            calls = {'appends':[], 'environments':[], 'prompts':[]}
            previous = {k:getattr(self.agent,k) for k in
                        ('provider_record','resolve_command','provider_prompt_for_turn',
                         'provider_authority_environment')}
            real_hospital = self.agent.px_hospital
            def captured_hospital(command,*params,**kwargs):
                if command=='message-append':
                    calls['appends'].append(params)
                    raise RuntimeError('RW08_MESSAGE_APPEND_BOUNDARY')
                return real_hospital(command,*params)
            self.agent.px_hospital = captured_hospital
            self.agent.provider_record = lambda provider_id: {
                'command':'python3','dialect':'hermes-stream-json',
                'startArgs':['chat'],'resumeArgs':['chat']}
            self.agent.resolve_command = lambda command: sys.executable
            self.agent.provider_prompt_for_turn = lambda prompt,context,extra: (
                calls['prompts'].append(context) or prompt)
            self.agent.provider_authority_environment = lambda session_id,assignment: (
                calls['environments'].append(assignment) or ({},{'allowed':['READ']}))
            def restore():
                for k,v in previous.items(): setattr(self.agent,k,v)
            self.addCleanup(restore)
            args = SimpleNamespace(
                session_id='fresh-doctor-B',working_directory=str(bed),
                prompt_json_stdin=False,prompt_stdin=False,
                prompt='test oversized Patient decision handling',
                author_id='operator',message_type='chat',supplemental_context='')
            with self.assertRaisesRegex(RuntimeError,
                                         'PATIENT.*REFUSED|CONTINUITY.*REFUSED'):
                self.agent._run_turn_unlocked(args)
            self.assertEqual(calls['appends'],[], 'No outgoing message may be persisted')
            self.assertEqual(calls['environments'],[], 'No provider environment constructed')
            self.assertEqual(calls['prompts'],[], 'No provider prompt constructed')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 nurse2_rw01_rw02_actual_checkout_regression.py /path/to/PX-checkout [-v]',file=sys.stderr)
        raise SystemExit(2)
    source = sys.argv.pop(1)
    PatientSuccessionActualSource.checkout = Path(source)
    unittest.main()