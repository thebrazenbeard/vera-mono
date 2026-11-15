"""Audit raw synthetic local tone-model results and model-authored challenge oracle.

Source parser comparison is an implementation consistency check, not a
human-quality or independent social-skill verdict.
"""
from pathlib import Path
import hashlib
import json

from vera_core.social_active_state import route_styled_boundary_reply

ROOT=Path(__file__).resolve().parents[1]
TRIAL=ROOT/"evaluations"/"social_bounded_scene_direction_qwen_seed109_20261115.jsonl"
FIXTURE=ROOT/"evaluations"/"social_bounded_scene_direction_v1.json"
OUTPUT=ROOT/"evaluations"/"social_bounded_context_trial_audit_20261115.json"
CHALLENGE_ORIGINAL=ROOT/"evaluations"/"social_bounded_challenge_qwen4b_seed107_20261115.json"

DIGESTS={
    "qwen3.5:0.8b":"de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c",
    "qwen3:4b-instruct":"0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0",
}


def audit() -> None:
    raw=TRIAL.read_bytes()
    rawsha=hashlib.sha256(raw).hexdigest()
    assert rawsha=="ac00f4bfe925f838d74e714b0388afa5921558b1422b1202cf9418e96536c2e1"
    lines=raw.splitlines()
    rows=[json.loads(x) for x in lines]
    fixturebytes=FIXTURE.read_bytes()
    fixture_sha=hashlib.sha256(fixturebytes).hexdigest()
    cases=json.loads(fixturebytes)["cases"]
    assert len(rows)==18 and len(cases)==9
    indexed={x["id"]:x for x in cases}
    assert len(indexed)==9
    stats={m:{"matches":0,"author_cues":0,"bypasses":0,"actual_calls":0,
              "selected_tokens":{}} for m in DIGESTS}
    seen=set()
    for record in rows:
        case=record["case"]
        model=record["model"]
        item=case["id"]
        key=(model,item)
        assert model in DIGESTS and key not in seen
        seen.add(key)
        assert record["schema"]=="VERA_SOCIAL_BOUNDED_DIRECTION_MODEL_RAW_V1"
        assert case==indexed[item] and record["fixture_sha256"]==fixture_sha
        assert record["model_digest"]==DIGESTS[model] and record["seed"]==109
        result=record["result"]
        assert result["evidence"]==record["source_evidence"]
        assert result["actual_user_identity_verified"] is False
        assert result["external_effect_authorized"] is False
        assert result["canonical_memory_admitted"] is False
        calls=record["actual_model_calls"]
        if item=="unknown_does_not_use_direction":
            assert record["source_status"]=="UNRESOLVED"
            assert not calls and not result["model_used"]
            assert result["answer"]=="UNKNOWN" and result["status"]=="UNRESOLVED"
            stats[model]["bypasses"]+=1
            continue
        assert record["source_status"]=="RESOLVED"
        assert record["source_evidence"]==[["Nia may not read Omar's messages",1]]
        assert len(calls)==1 and result["model_used"]
        call=calls[0]
        req=call["request"]
        assert req["model"]==model and req["stream"] is False and req["think"] is False
        assert req["options"]=={
            "temperature":0,"seed":109,"num_predict":24,"num_ctx":2048,
        }
        assert "tools" not in req
        assert len(req["messages"])==2
        assert req["messages"][0]["role"]=="system"
        assert req["messages"][1]["role"]=="user"
        context=case["scene_direction"]
        if context is None:
            assert "Untrusted fictional scene direction" not in req["messages"][1]["content"]
        else:
            assert context in req["messages"][1]["content"]
        token=call["response"]["message"]["content"].strip()
        assert token in ("DIRECT","GENTLE","FIRM","CASUAL")
        assert result["status"]=="SOURCE_STYLED_"+token
        if item.startswith("owner_"):
            assert result["answer"].startswith("Omar could tell Nia, ")
            assert "read my messages" in result["answer"]
        else:
            assert result["answer"].startswith("Nia could tell Omar, ")
            assert "won't read" in result["answer"]
        assert "may read Omar" not in result["answer"]
        stats[model]["actual_calls"]+=1
        stats[model]["selected_tokens"][item]=token
        expectation=case["author_style_expectation"]
        if expectation is not None:
            stats[model]["author_cues"]+=1
            stats[model]["matches"]+=int(token==expectation)
    assert len(seen)==18
    assert stats["qwen3.5:0.8b"]["matches"]==5
    assert stats["qwen3:4b-instruct"]["matches"]==6
    assert all(v["author_cues"]==6 and v["bypasses"]==1
               and v["actual_calls"]==8 for v in stats.values())
    challenge=CHALLENGE_ORIGINAL.read_bytes()
    challenge_rows=json.loads(challenge)["cases"]
    assert len(challenge_rows)==8
    qa=[]
    for c in challenge_rows:
        result=route_styled_boundary_reply(c["turns"],lambda _:"DIRECT")
        observed=("grounded" if result.status=="SOURCE_STYLED_DIRECT"
                  else "unknown" if result.status=="UNRESOLVED"
                  else "unsupported")
        qa.append({
            "id":c["id"],"author_oracle":c["expected_route"],
            "implementation_status":result.status,
            "observed_route":observed,
            "oracle_matches":observed==c["expected_route"],
            "final_turn_is_question":c["turns"][-1].endswith("?"),
        })
    assert sum(x["oracle_matches"] for x in qa)==4
    assert sum(not x["final_turn_is_question"] for x in qa)==6
    audit_payload={
        "schema":"VERA_SOCIAL_BOUNDED_CONTEXT_TRIAL_POSTHOC_AUDIT_V1",
        "raw_sha256":rawsha,
        "fixture_sha256":fixture_sha,
        "record_count":len(rows),
        "model_calls":16,
        "no_model_bypasses":2,
        "model_digests":DIGESTS,
        "seed":109,
        "same_worker_author_style_expectations":stats,
        "different_model_fixture_author":{
            "model":"qwen3:4b-instruct","seed":107,
            "raw_sha256":hashlib.sha256(challenge).hexdigest(),
            "cases":qa,"oracle_agreement":4,"cases_total":8,
            "no_final_question":6,
            "disposition":"FAILED_ORACLE_GATE_NOT_VALID_HOLDOUT",
        },
        "human_independent_review":False,
        "source_only":True,
        "native_runtime_consumed":False,
        "canonical_memory_admitted":False,
        "external_effect_authorized":False,
    }
    serialized=json.dumps(audit_payload,sort_keys=True,indent=2)+"\n"
    if OUTPUT.exists():
        if OUTPUT.read_bytes()!=serialized.encode("utf8"):
            raise AssertionError("stored audit differs from recomputation")
    else:
        OUTPUT.write_text(serialized,encoding="utf8",newline="\n")
    print("AUDIT_PASS",len(rows),"RAW_SHA",rawsha,
          "FIXTURE_SHA",fixture_sha)
    print("MATCHES",[(m,stats[m]["matches"],stats[m]["author_cues"])
                    for m in DIGESTS])
    print("QA_ORACLE_PASS",4,"/",8,"INVALID_FINAL_QUESTIONS",6)
    print("QA_RAW_SHA",hashlib.sha256(challenge).hexdigest())
    print("AUDIT_SHA",hashlib.sha256(OUTPUT.read_bytes()).hexdigest())


if __name__=="__main__":
    audit()
