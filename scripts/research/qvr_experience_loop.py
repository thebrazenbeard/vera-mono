"""Isolated, finite Goal 1 *research* session using the selected QVR.

Run: python scripts/research/qvr_experience_loop.py run

This launches a local-only evaluator child process, then separate QVR learner
processes for inquiry, feedback revision and cold-process transfer. The
controller never sends hidden evaluator answers to the learner model before
the selected probe or scoring. It uses a tiny hand-authored rule family.
No tools/effects, no canonical memory, no service activation, no model tuning.
The evaluator shares the host/user account: this is NOT independent custody.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

TRAIN = {"train-a": "000", "train-b": "001", "train-c": "100", "train-d": "110"}
HOLDOUT = {"hidden-e": "010", "hidden-f": "011", "hidden-g": "101", "hidden-h": "111"}
MODEL_TAG = "qwen3:4b-instruct"
ROUTE = "GOAL1_LOCAL_RESEARCH"
SCOPE = "SYNTHETIC_LOCAL_INFERENCE_TEST"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def classify(rule: str, bits: str) -> str:
    if type(bits) is not str or re.fullmatch(r"[01]{3}", bits) is None or rule not in ("A", "B"):
        raise ValueError("invalid symbolic candidate or input")
    return str(int(bits.count("1")>=2)) if rule=="A" else str(bits.count("1")%2)


def predict_all(rule: str, cases: dict[str,str]) -> dict[str,str]:
    if type(cases) is not dict or not cases or len(cases)>64:
        raise ValueError("invalid bounded cases")
    return {key:classify(rule,bits) for key,bits in sorted(cases.items())}


def choose_rule(output: str) -> str | None:
    if type(output) is not str:return None
    val=output.strip()
    return val if val in ("A", "B") else None


def choose_query(output: str) -> tuple[str,str] | None:
    if type(output) is not str:return None
    match=re.fullmatch(r"([AB]) (train-[a-d])",output.strip())
    if match is None:return None
    case=match.group(2)
    if case not in TRAIN or classify("A",TRAIN[case])==classify("B",TRAIN[case]):
        return None
    return match.group(1),case


def verify_feedback(case: str, label: str, *, model_revision: str | None) -> dict:
    if case not in TRAIN or type(label) is not str or label not in ("0","1"):
        raise ValueError("invalid evaluator feedback")
    predictions={r:classify(r,TRAIN[case]) for r in ("A","B")}
    surviving=[r for r,answer in predictions.items() if answer==label]
    if len(surviving)!=1:
        raise ValueError("feedback cannot uniquely distinguish candidates")
    return {"case_id":case,"features":TRAIN[case],"observed_label":label,
            "evidence_rule":surviving[0],"model_revision":model_revision,
            "model_disagreed":model_revision!=surviving[0]}


@contextmanager
def evaluator_subprocess():
    """No external network or effect transport. Hidden state stays in child RAM."""
    proc=subprocess.Popen(
        [sys.executable,"-B",str(Path(__file__).resolve()),"__evaluator__"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        text=True,bufsize=1,encoding="utf-8",
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=4)
        for stream in (proc.stdin,proc.stdout):
            if stream:stream.close()


def eval_request(proc: subprocess.Popen, value: dict) -> dict:
    if proc.poll() is not None or proc.stdin is None or proc.stdout is None:
        raise RuntimeError("evaluator process unavailable")
    proc.stdin.write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
    proc.stdin.flush()
    raw=proc.stdout.readline()
    if not raw or len(raw)>8192:
        raise RuntimeError("invalid evaluator reply")
    response=json.loads(raw)
    if type(response) is not dict:
        raise RuntimeError("evaluator replied non-object")
    return response


def _evaluator_loop() -> None:
    secret=("A","B")[secrets.randbelow(2)]
    nonce=secrets.token_hex(16)
    labels={case:classify(secret,bits) for case,bits in {**TRAIN,**HOLDOUT}.items()}
    precommit=_digest({"nonce":nonce,"labels":labels,"secret":secret,"all_inputs":{**TRAIN,**HOLDOUT}})
    phase="NEW"
    probed=None
    for raw in sys.stdin:
        try:
            req=json.loads(raw)
            if type(req) is not dict:raise ValueError("not object")
            op=req.get("action")
            if op=="start" and phase=="NEW" and set(req)=={"action"}:
                phase="INQUIRY"
                result={"status":"INQUIRY","train":TRAIN,"probe_budget":1,"precommit":precommit}
            elif op=="probe" and set(req)=={"action","id"}:
                if phase!="INQUIRY" or probed is not None or req["id"] not in TRAIN:
                    result={"error":"PROBE_DENIED"}
                else:
                    probed=req["id"]
                    result={"status":"FEEDBACK","id":probed,"bits":TRAIN[probed],"label":labels[probed]}
            elif op=="holdout" and set(req)=={"action"}:
                if phase!="INQUIRY" or probed is None:
                    result={"error":"INVALID_PHASE"}
                else:
                    phase="PREDICTION";result={"status":"PREDICTION","inputs":HOLDOUT}
            elif op=="score" and set(req)=={"action","predictions"}:
                if phase=="SCORED":result={"error":"TRIAL_CLOSED"}
                elif phase!="PREDICTION":result={"error":"INVALID_PHASE"}
                else:
                    proposed=req["predictions"]
                    if (type(proposed) is not dict or set(proposed)!=set(HOLDOUT)
                            or any(type(v) is not str or v not in ("0","1") for v in proposed.values())):
                        result={"error":"INVALID_PREDICTIONS"}
                    else:
                        phase="SCORED"
                        result={"status":"SCORED",
                                "correct":sum(proposed[k]==labels[k] for k in HOLDOUT),
                                "attempted":len(HOLDOUT),
                                "post_score_true_rule":secret,
                                "post_score_truth":{k:labels[k] for k in HOLDOUT},
                                "precommit":precommit,
                                "prediction_sha256":_digest(proposed)}
            else:result={"error":"INVALID_REQUEST"}
        except (ValueError,TypeError):
            result={"error":"INVALID_REQUEST"}
        print(json.dumps(result,sort_keys=True,separators=(",",":")),flush=True)


def validate_lab_state_root(candidate: Path) -> Path:
    """Reject canonical/foreign state roots before any QVR or provider access."""
    candidate=Path(candidate)
    parent=candidate.parent
    expected_parent=Path(tempfile.gettempdir()).resolve()
    if (candidate.name!="isolated-state" or candidate.is_symlink()
            or not candidate.is_dir() or parent.is_symlink()
            or parent.parent.resolve()!=expected_parent
            or not parent.name.startswith("vera-goal1-self-learning-")
            or parent.resolve()!=parent.absolute()):
        raise ValueError("refusing non-synthetic state path")
    return candidate.resolve()


def _qvr_setup(state_dir: Path):
    repo=Path(__file__).resolve().parents[2]
    for path in sorted((repo/"packages").glob("*/src")):
        if str(path) not in sys.path:sys.path.insert(0,str(path))
    from vera_core import QualifiedVeraRuntime,VeraStateDirectory
    from vera_core.local_cognition import LocalCognitionGate,InferencePermit,EXACT_TEST_SCOPE
    state_dir=validate_lab_state_root(state_dir)
    with urlopen("http://127.0.0.1:11434/api/tags",timeout=6) as response:
        entries=json.load(response)["models"]
    matches=[m for m in entries if m.get("name")==MODEL_TAG]
    if len(matches)!=1:raise RuntimeError("selected model missing")
    tag=matches[0]["digest"]
    gate=LocalCognitionGate(model=MODEL_TAG,expected_digest=tag,armed=True,timeout=10)
    state=VeraStateDirectory(state_dir,project_id="goal1-synthetic-local-loop",identity_id="goal1-isolated-vera")
    runtime=QualifiedVeraRuntime.from_state_directory(state,
        local_cognition_transport=gate,local_cognition_route_ref=ROUTE)
    return runtime,InferencePermit(model=MODEL_TAG,digest=tag,scope=EXACT_TEST_SCOPE),tag


def _worker(mode: str, packet: dict) -> dict:
    state=Path(packet["state"]).resolve()
    qvr,permit,model_digest=_qvr_setup(state)
    def ask(prompt: str, invocation: str) -> dict:
        t=time.monotonic()
        r=qvr.consume_local_cognition(prompt,permit=permit,invocation_id=invocation,max_tokens=64)
        return {"text":r.text,"response_sha256":r.response_sha256,"prompt_sha256":r.prompt_sha256,
                "seconds":round(time.monotonic()-t,2)}
    if mode=="inquire":
        prompt=("An evaluator has secretly chosen rule A or B. A means at least TWO ones in three bits. "
               "B means an ODD number of ones. Training inputs without answers are "
               "train-a=000 train-b=001 train-c=100 train-d=110. "
               "Before feedback, commit an initial rule guess and choose the single most informative experiment. "
               "Return EXACTLY two tokens, example A train-b, but decide for yourself. No explanation.")
        answer=ask(prompt,"goal1-query")
        result=choose_query(answer["text"])
        return {"phase":mode,"valid":bool(result),"initial_guess":result[0] if result else None,
                "query":result[1] if result else None,"model_receipt":answer,
                "runtime_pid":os.getpid(),"reported_model_digest":model_digest,
                "journal_count":len(qvr.local_cognition_history())}
    if mode=="revise":
        observed=packet["feedback"]
        case=observed["id"]
        label=observed["label"]
        prompt=(f"Rule A means at least two ones; B means odd number of ones. "
                f"Your chosen experiment {case} has bits {observed['bits']}. "
                f"An external evaluator returned label {label}. Which rule remains consistent? "
                "Reply EXACTLY A or B and nothing else.")
        answer=ask(prompt,"goal1-revise")
        evidence=verify_feedback(case,label,model_revision=choose_rule(answer["text"]))
        from vera_memory import AdmissionRequest,MemoryClass
        memory=qvr.lifecycle.memory
        record={"schema":"GOAL1_PROVISIONAL_BOUNDED_EXPERIENCE_V1",
             "status":"UNQUALIFIED_PROVISIONAL", "rule":evidence["evidence_rule"],
             "case":case,"label":label,"precommit":packet["precommit"],
             "model_disagreed":evidence["model_disagreed"],
             "source":"LOCAL_QVR_SYNTHETIC_RULE_ELIMINATION"}
        req=AdmissionRequest(
             record_id="goal1-synthetic-provisional-1",
             text=json.dumps(record,sort_keys=True),
             memory_class=MemoryClass.WORKING_PROJECT,
             source_actor="qvr-goal1-research-controller",
             authority_ref="NO_AUTHORITY_SYNTHETIC_ONLY",
             privacy_ref="LOCAL_NONCANONICAL_SYNTHETIC",
             provenance_refs=("qvr:goal1-query","qvr:goal1-revise","evaluator:"+packet["precommit"]),
             operation_id="goal1-provisional-1",
             project_id=memory.project_id,governed_identity_id=memory.identity_id)
        memory.admit(req,expected_head=memory.current_head)
        return {"phase":mode,"provisional_rule":record["rule"],
           "model_answer":answer["text"],"model_disagreed":record["model_disagreed"],
           "memory_head":memory.current_head,"runtime_pid":os.getpid(),
           "model_receipt":answer,"journal_count":len(qvr.local_cognition_history())}
    if mode=="transfer":
        memory=qvr.lifecycle.memory
        data=memory.read("goal1-synthetic-provisional-1")
        if (data.status!="CURRENT" or data.project_id!=memory.project_id
                or data.governed_identity_id!=memory.identity_id):
            raise RuntimeError("provisional memory wrong scope")
        record=json.loads(data.text)
        if record["status"]!="UNQUALIFIED_PROVISIONAL" or record["precommit"]!=packet["precommit"]:
            raise RuntimeError("memory/evaluator mismatch")
        rule=record["rule"]
        prompt=(f"From earlier Vera working-project experience, one query {record['case']} returned "
                f"label {record['label']}. Evidence arbitration retained provisional rule {rule}; "
                "A means >=2 ones, B means odd ones. Which rule applies to new examples? "
                "Reply EXACTLY A or B.")
        try:
            answer=ask(prompt,"goal1-transfer")
            model_agrees=choose_rule(answer["text"])==rule
            model_error=None
        except Exception as e:
            answer=None;model_agrees=False;model_error=type(e).__name__
        return {"phase":mode,"rule":rule,"predictions":predict_all(rule,packet["holdout"]),
             "model_agrees":model_agrees,"model_receipt":answer,
             "model_error":model_error,"runtime_pid":os.getpid(),
             "memory_head":memory.current_head,"journal_count":len(qvr.local_cognition_history())}
    raise ValueError("unknown worker mode")


def _call_worker(mode: str, payload: dict) -> dict:
    p=subprocess.run([sys.executable,"-B",str(Path(__file__).resolve()),
                      "__worker__",mode],input=json.dumps(payload),
                     capture_output=True,text=True,encoding="utf-8",timeout=48)
    if p.returncode:
        raise RuntimeError(f"{mode} worker failed: {p.stderr[-320:]}")
    result=json.loads(p.stdout)
    if type(result) is not dict:raise RuntimeError("worker returned wrong type")
    return result


def run_once() -> dict:
    """One whole bounded learning experiment runs without ChatGPT step relays."""
    root=Path(tempfile.mkdtemp(prefix="vera-goal1-self-learning-")).resolve()
    state=root/"isolated-state"
    state.mkdir()
    packets=[]
    with evaluator_subprocess() as evaluator:
        initial=eval_request(evaluator,{"action":"start"})
        if initial.get("status")!="INQUIRY":raise RuntimeError("evaluator not ready")
        payload={"state":str(state),"precommit":initial["precommit"]}
        inquiry=_call_worker("inquire",payload)
        packets.append({"phase":"inquire","worker":inquiry})
        if not inquiry.get("valid"):
            result={"status":"INVALID_MODEL_INQUIRY","root":str(root),"events":packets}
        else:
            # Preserve the initial pre-outcome guess BEFORE obtaining the label.
            pre=root/"initial_prediction.json"
            pre.write_text(json.dumps({"guess":inquiry["initial_guess"],"query":inquiry["query"],
                 "precommit":initial["precommit"],"pid":inquiry["runtime_pid"]},sort_keys=True))
            observation=eval_request(evaluator,{"action":"probe","id":inquiry["query"]})
            if observation.get("status")!="FEEDBACK":raise RuntimeError("invalid evaluator probe")
            packets.append({"phase":"probe","data":observation})
            revision=_call_worker("revise",{**payload,"feedback":observation})
            packets.append({"phase":"revise","worker":revision})
            opened=eval_request(evaluator,{"action":"holdout"})
            if opened.get("status")!="PREDICTION":raise RuntimeError("holdout not released")
            transfer=_call_worker("transfer",{**payload,"holdout":opened["inputs"]})
            packets.append({"phase":"transfer","worker":transfer})
            if len({inquiry["runtime_pid"],revision["runtime_pid"],transfer["runtime_pid"]})!=3:
                raise RuntimeError("missing distinct cold QVR processes")
            predictions=transfer["predictions"]
            committed=root/"pre_score_predictions.json"
            committed.write_text(json.dumps({"candidate":predictions,
                "frozen":predict_all(inquiry["initial_guess"],opened["inputs"])},sort_keys=True))
            scored=eval_request(evaluator,{"action":"score","predictions":predictions})
            if scored.get("status")!="SCORED":raise RuntimeError("score denied")
            frozen=predict_all(inquiry["initial_guess"],opened["inputs"])
            frozen_correct=sum(frozen[k]==scored["post_score_truth"][k] for k in frozen)
            if scored["correct"]<frozen_correct:
                verdict="NEGATIVE_TRANSFER"
            elif scored["correct"]>frozen_correct:
                verdict="BOUNDED_MEASURED_GAIN"
            else:
                verdict="NO_MEASURED_GAIN"
            result={"status":verdict,"source":"selected-QVR-local-Ollama",
                "exact_scope":"TWO_DEVELOPER_SUPPLIED_BOOLEAN_RULES",
                "evaluator_precommit":initial["precommit"],
                "candidate_correct":scored["correct"],"frozen_correct":frozen_correct,
                "total_hidden":scored["attempted"],"model_disagreed":revision["model_disagreed"],
                "model_reused_after_restart":transfer["model_agrees"],
                "separate_qvr_pids":[inquiry["runtime_pid"],revision["runtime_pid"],transfer["runtime_pid"]],
                "actual_model_journal_count":transfer["journal_count"],
                "root":str(root),"events":packets,"scored":scored}
    result["claim_ceiling"]="SYNTHETIC_INDEPENDENT_PROCESS_LOOP_NOT_INDEPENDENT_HOST_NOT_GENERAL_AGI"
    (root/"result.json").write_text(json.dumps(result,sort_keys=True,indent=2))
    return result


if __name__=="__main__":
    try:
        if len(sys.argv)==2 and sys.argv[1]=="__evaluator__":
            _evaluator_loop()
        elif len(sys.argv)==3 and sys.argv[1]=="__worker__":
            value=_worker(sys.argv[2],json.load(sys.stdin))
            print(json.dumps(value,sort_keys=True))
        elif len(sys.argv)==2 and sys.argv[1]=="run":
            print(json.dumps(run_once(),sort_keys=True),flush=True)
        else:
            raise SystemExit("usage: qvr_experience_loop.py run")
    except Exception as exc:
        print(f"Goal 1 experiment failed: {type(exc).__name__}: {exc}",file=sys.stderr)
        raise SystemExit(2)
