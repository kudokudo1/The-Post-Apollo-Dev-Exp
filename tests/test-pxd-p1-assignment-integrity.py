#!/usr/bin/env python3
"""Hospital Nurse 2: read-only P1 acceptance probes against a PX checkout.

Usage: python3 nurse2_p1_checkout_regression_UNRUN.py /path/to/The-Post-Apollo-Dev-Exp
Recommended checkout: PR #61 preview branch, in a disposable clone/worktree.
All DB writes go to private sqlite3 :memory: only. No provider launches, no git writes.

EXPECTED ON CURRENT PR #61: a nonzero result, exposing known integrity defects.
EXPECTED AFTER OWNER'S FIX: every check PASS and exit 0.
NOTE: tests import the actual bin/px-hospital-store and bin/px-agent source files.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


def fixture(store):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    store.migrate(db)
    db.execute('INSERT INTO patients(patient_id,repository,label) VALUES(?,?,?)',('P','test/repo','P'))
    for room, team in [('A','team-a'),('B','team-b')]:
        db.execute('''INSERT INTO rooms(room_id,patient_id,team,branch,bed_path,
            doctor_id,current_assignment_id) VALUES(?,?,?,?,?,?,?)''',
            (room,'P',team,'feature/'+room.lower(),'/tmp/fakebed-'+room,'doctor-'+room,''))
    rows=[('A','ACTIVE',['READ','TEST'],'A order'),
          ('B','ACTIVE',['READ','EDIT','COMMIT'],'B secret order'),
          ('A','PAUSED',['READ','EDIT'],'A paused order')]
    ids=[]
    for room,status,perms,title in rows:
        cur=db.execute('''INSERT INTO assignments(room_id,patient_id,title,goal_md,
            permissions_json,checklist_md,status) VALUES(?,?,?,?,?,?,?)''',
            (room,'P',title,'Goal '+title,json.dumps(perms),'[ ] '+title,status))
        ids.append(cur.lastrowid)
    db.execute("INSERT INTO sessions(session_id,room_id,doctor_id,provider_id) VALUES('fresh-doctor-B','A','doctor-B','mock')")
    db.commit()
    return db,ids


def set_link(db,id):
    db.execute('UPDATE rooms SET current_assignment_id=? WHERE room_id=?',
               (str(id) if id is not None else '', 'A'))
    db.commit()


def requires_integrity_failure(function):
    try:
        value = function()
    except (ValueError, RuntimeError) as e:
        return True, type(e).__name__ + ': ' + str(e)
    return False, 'unexpected success: ' + repr(value)[:210]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('checkout',type=Path)
    args=p.parse_args()
    checkout=args.checkout.resolve()
    store_path=checkout/'bin'/'px-hospital-store'
    agent_path=checkout/'bin'/'px-agent'
    if not store_path.is_file() or not agent_path.is_file():
        p.error('PX checkout missing bin/px-hospital-store or bin/px-agent')
    sys.path.insert(0,str(checkout/'bin'))
    store=load('p1_hospital_store_readonly',store_path)
    agent=load('p1_agent_readonly',agent_path)
    if not hasattr(store,'assignment_authority'):
        print('Missing assignment_authority resolver (expected on PR #61)')
        return 2
    db,ids=fixture(store)
    a,foreign,paused=ids
    checks=[]

    def check(name, fn):
        try:
            ok, info=fn()
        except Exception as e:
            ok,info=False,f'unexpected {type(e).__name__}: {e}'
        checks.append(ok)
        print(f'{"PASS" if ok else "FAIL"} {name}: {info}')

    set_link(db,None)
    def unassigned_read():
        result=store.assignment_authority(db,room_id='A',permission='READ')
        ok=result.get('allowed') is True and result.get('source')=='READ_ONLY_DEFAULT' and result.get('assignmentId')==''
        return ok,str(result)
    check('unassigned Room receives READ-only default',unassigned_read)
    def unassigned_edit():
        result=store.assignment_authority(db,room_id='A',permission='EDIT')
        return result.get('allowed') is False and result.get('source')=='READ_ONLY_DEFAULT',str(result)
    check('unassigned Room refuses EDIT',unassigned_edit)
    set_link(db,a)
    def correct():
        result=store.assignment_authority(db,room_id='A',permission='TEST')
        return result.get('allowed') is True and result.get('assignmentId')==str(a),str(result)
    check('own ACTIVE Assignment retains own authority',correct)

    set_link(db,foreign)
    check('foreign ACTIVE link refuses EDIT (not grant)',lambda:requires_integrity_failure(
        lambda:store.assignment_authority(db,room_id='A',permission='EDIT')))
    check('foreign ACTIVE link refuses even READ',lambda:requires_integrity_failure(
        lambda:store.assignment_authority(db,room_id='A',permission='READ')))
    check('foreign ACTIVE link refuses Team/repo COMMIT',lambda:requires_integrity_failure(
        lambda:store.assignment_authority(db,team='team-a',repository='test/repo',permission='COMMIT')))

    set_link(db,paused)
    check('PAUSED linked Assignment is not treated as unassigned',lambda:requires_integrity_failure(
        lambda:store.assignment_authority(db,room_id='A',permission='READ')))
    set_link(db,999999)
    check('dangling Assignment link has explicit failure',lambda:requires_integrity_failure(
        lambda:store.assignment_authority(db,room_id='A',permission='READ')))

    def mock_hospital(cmd,*params):
        if cmd=='session':
            return store.session_record(db,params[0])
        if cmd=='room':
            return store.room_record(db,params[0])
        if cmd=='assignment':
            return store.assignment_record(db,int(params[0]))
        if cmd in ('chart-entries','messages','checkpoints','room-reports'):
            return []
        raise AssertionError('unhandled mock ' + cmd)

    agent.px_hospital=mock_hospital
    agent.select_relevant_room_history=lambda *args: []
    agent.collect_git_report_evidence=lambda *args: {'status':'UNAVAILABLE'}
    set_link(db,foreign)
    check('Doctor B context rejects foreign work and permissions',lambda:requires_integrity_failure(
        lambda:agent.live_context_payload('fresh-doctor-B', query_text='continue')))
    set_link(db,paused)
    check('Doctor B context rejects PAUSED work and permissions',lambda:requires_integrity_failure(
        lambda:agent.live_context_payload('fresh-doctor-B', query_text='continue')))
    set_link(db,a)
    def own_context():
        context=agent.live_context_payload('fresh-doctor-B',query_text='continue')
        ok=(context['room']['id']=='A' and context['assignment']['id']==str(a)
            and context['assignment']['roomId']=='A'
            and 'COMMIT' not in context['authority']['allowed'])
        return ok,f"room={context['room']['id']}, assignment={context['assignment'].get('id')}, authority={context['authority']['allowed']}"
    check('Doctor B context accepts own ACTIVE Assignment',own_context)

    print(f'\nP1 actual-source checkout test: {sum(checks)}/{len(checks)} PASS')
    if not all(checks):
        print('P1 NOT ACCEPTED. Do not treat expected unsafe behavior as a passing gate.')
        return 1
    return 0

if __name__=='__main__':
    raise SystemExit(main())