#!/usr/bin/env python3
"""Run Nurse 2's independent RW eight-case test on an EXACT PX checkout.

Read-only with respect to supplied checkout. The harness uses in-memory SQLite,
temporary Git Bed and mocked PX calls; never calls a real provider. Runner
refuses a mismatched commit and records a per-case JSON result outside checkout.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REQUIRED_SHA = "7ce911836c9fcbe1039e675e2575c86e92a31d1e"
HARNESS = Path(__file__).with_name("nurse2_rw01_rw02_actual_checkout_regression_v2.py")
EXPECTED = (
    "test_rw01_low_priority_active_patient_decision_not_displaced",
    "test_rw02_active_patient_decision_body_not_silently_clipped",
    "test_rw03_excess_patient_required_content_delivered_or_explicitly_refused",
    "test_rw04_other_patient_context_cannot_receive_patient_p_decisions",
    "test_rw05_same_patient_other_room_shares_patient_not_room_context",
    "test_rw06_wrong_patient_store_response_must_not_leak_into_prompt",
    "test_rw07_existing_s2_room_handoff_positive_control",
    "test_rw08_oversized_patient_decision_refuses_before_provider_dispatch",
)

def execute(checkout: Path, output: Path):
    checkout = checkout.expanduser().resolve()
    output = output.expanduser().resolve()
    status = {
        "testHarness": str(HARNESS), "targetCheckout": str(checkout),
        "requiredCommit": REQUIRED_SHA, "actualCommit": None,
        "executed": False, "success": False,
        "cases": {key:{"result":"NOT_RUN"} for key in EXPECTED},
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "runLog":str(output.with_suffix('.log')),
        "notes":[],
    }
    def save_and_return(rc):
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(status,indent=2,sort_keys=True)+"\n")
        print(json.dumps({"executed":status["executed"],"success":status["success"],"actualCommit":status["actualCommit"],"cases":status["cases"],"notes":status["notes"]},indent=2))
        return rc
    if not checkout.is_dir():
        status["notes"].append("No checkout directory; exact-source gate not executed")
        return save_and_return(2)
    try:
        g=subprocess.run(["git","-C",str(checkout),"rev-parse","HEAD"],capture_output=True,text=True,timeout=10,check=True)
    except (OSError,subprocess.SubprocessError) as e:
        status["notes"].append("Cannot verify checkout commit: "+str(e))
        return save_and_return(2)
    status["actualCommit"] = g.stdout.strip()
    if status["actualCommit"] != REQUIRED_SHA:
        status["notes"].append("Commit mismatch; refused to run against another revision")
        return save_and_return(2)
    needed=["bin/px-agent","bin/px-hospital-store","bin/hospital_target_preflight.py","tests/test-pxd-p1-assignment-integrity.py"]
    absent=[x for x in needed if not (checkout/x).is_file()]
    if absent:
        status["notes"].append("Required checkout files missing: "+", ".join(absent))
        return save_and_return(2)
    if not HARNESS.is_file():
        status["notes"].append("Independent Nurse 2 harness is missing")
        return save_and_return(2)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p=subprocess.run([sys.executable,"-B",str(HARNESS),str(checkout),"-v"],text=True,capture_output=True,env=env,timeout=180,check=False)
    status["executed"] = True
    log=p.stdout+"\n"+p.stderr
    output.with_suffix('.log').write_text(log)
    found=[]
    for line in log.splitlines():
        match=re.match(r"^(test_\w+)\s+\([^)]*\)\s+\.\.\.\s+(ok|FAIL|ERROR|skipped.*)$",line)
        if match and match.group(1) in status["cases"]:
            case,result=match.groups()
            status["cases"][case]={"result":{"ok":"PASS","FAIL":"FAIL","ERROR":"ERROR"}.get(result,"SKIPPED")}
            found.append(case)
    status["success"] = (p.returncode == 0 and len(found) == len(EXPECTED) and
                         all(v["result"]=="PASS" for v in status["cases"].values()))
    status["notes"].append("Harness exit code: "+str(p.returncode))
    status["notes"].append("Cases found in execution log: "+str(len(found))+" / 8")
    if not status["success"]:
        status["notes"].append("Do not certify RW-01/RW-02 on this run")
    return save_and_return(0 if status["success"] else 1)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkout",type=Path,help="Exact SHA PX repository checkout")
    p.add_argument("--output",type=Path,default=Path("/mnt/data/nurse2_pr66_exact_harness_results.json"))
    args=p.parse_args()
    raise SystemExit(execute(args.checkout,args.output))