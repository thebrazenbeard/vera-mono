"""Explicit optional advisory boundary; never a runtime or effect authority.

Only public external APIs are called. No external implementation is bundled.
Installed optional packages execute in-process, not in a security sandbox: the
operator must select trustworthy, appropriately licensed packages separately.
"""

from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
import json


MAX_INPUT_BYTES = 65536
_CLASSES = frozenset({"DOC", "DEP_METADATA", "SOURCE_INSPECTION", "TEST", "BUILD",
                      "INSTALL", "REAL_SYSTEM_PROBE", "FORMAL_VERIFY"})
_INVALID = "INVALID_ADVISORY_INPUT: bounded strict JSON required"
_LABELS = {"source_advisory": True, "executed": False, "verified": False,
           "authority": "NONE", "evidence_origin": "CALLER_SUPPLIED_UNVERIFIED"}
_REASONS = frozenset({"SCOPE_MISMATCH_IGNORED", "DUPLICATED_OR_DEPENDENT_EVIDENCE_IGNORED",
    "MATCHING_FAILURE_OBSERVED", "REQUIRED_CLASSES_PRESENT", "REQUIRED_CLASSES_UNVERIFIED"})
_BLOCKERS = frozenset({"DISABLED_ACTION", "FAILED_ACTION", "EFFECT_NOT_ALLOWED", "COST_CEILING",
    "BOUNDED_SEARCH_LIMIT", "NO_ACTIONS", "UNMET_PRECONDITIONS_OR_NO_PATH"})


class _BoundedDiscard(io.TextIOBase):
    """Best-effort Python stream hygiene, not descriptor or process isolation."""

    def __init__(self):
        self.remaining = MAX_INPUT_BYTES
        self.exceeded = False

    def write(self, text):
        if type(text) is not str or len(text) > self.remaining:
            self.exceeded = True
            raise ValueError("optional component output limit")
        self.remaining -= len(text.encode("utf-8", errors="strict"))
        if self.remaining < 0:
            self.exceeded = True
            raise ValueError("optional component output limit")
        return len(text)


def _require(condition):
    if not condition:
        raise ValueError(_INVALID)


def _fields(value, required, optional=()):
    _require(type(value) is dict and set(required).issubset(value)
             and not set(value) - set(required) - set(optional))
    return value


def _text(value, limit=128):
    _require(type(value) is str and 1 <= len(value) <= limit and bool(value.strip())
             and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value))
    return value


def _rows(value):
    _require(type(value) is list and len(value) <= 64)
    return value


def _names(value):
    return tuple(_text(name) for name in _rows(value))


def _output_names(value, allowed):
    # Never iterate an arbitrary provider iterable or serialize its objects.
    _require(type(value) in (tuple, list) and len(value) <= 64)
    names = [_text(item) for item in value]
    _require(len(set(names)) == len(names) and set(names) <= allowed)
    return names


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(_INVALID)


def _read(stream):
    # A real CLI uses bytes, so the ceiling applies before UTF-8 decoding.
    raw = getattr(stream, "buffer", stream).read(MAX_INPUT_BYTES + 1)
    if type(raw) is str:  # In-process text streams used by hosts and tests.
        raw = raw.encode("utf-8", errors="strict")
    _require(type(raw) is bytes and len(raw) <= MAX_INPUT_BYTES)
    return json.loads(raw.decode("utf-8", errors="strict"),
                      object_pairs_hook=_no_duplicates, parse_constant=_nonfinite)


def _claim_request(document):
    doc = _fields(document, {"claim", "receipts"})
    claim = _fields(doc["claim"], {"claim_id", "subject_ref", "proposition", "required_classes"})
    normalized = {key: _text(claim[key], 4096 if key == "proposition" else 128)
                  for key in ("claim_id", "subject_ref", "proposition")}
    kinds = _names(claim["required_classes"])
    _require(bool(kinds) and len(set(kinds)) == len(kinds) and set(kinds) <= _CLASSES)
    normalized["required_classes"] = kinds
    receipts = []
    for row in _rows(doc["receipts"]):
        _fields(row, {"receipt_id", "claim_id", "subject_ref", "source_group",
                      "kind", "outcome", "claim_digest"})
        item = {key: _text(value) for key, value in row.items()}
        _require(item["kind"] in _CLASSES and item["outcome"] in {"PASS", "FAIL"})
        digest = item["claim_digest"]
        _require(len(digest) == 64 and all(c in "0123456789abcdef" for c in digest))
        receipts.append(item)
    return normalized, receipts


def _zero(value):
    _require(type(value) is int and value == 0)
    return value


def _opportunity_request(document):
    doc = _fields(document, {"goal", "initial_capabilities", "actions", "allowed_effects", "cost_ceiling"},
                  {"granted_approvals", "failed_actions", "max_steps"})
    request = {"goal": _text(doc["goal"]), "cost_ceiling": _zero(doc["cost_ceiling"])}
    for key in ("initial_capabilities", "allowed_effects", "granted_approvals", "failed_actions"):
        request[key] = _names(doc.get(key, []))
    steps = doc.get("max_steps", 16)
    _require(type(steps) is int and 1 <= steps <= 32)
    request["max_steps"] = steps
    actions, ids = [], set()
    for row in _rows(doc["actions"]):
        _fields(row, {"id", "requires", "provides", "effects"},
                {"cost", "required_approvals", "provenance", "disabled"})
        action = {"id": _text(row["id"]), "cost": _zero(row.get("cost", 0)),
                  "disabled": row.get("disabled", False),
                  "provenance": _text(row.get("provenance", "caller_supplied_unverified"), 512)}
        _require(type(action["disabled"]) is bool and action["id"] not in ids)
        ids.add(action["id"])
        for key in ("requires", "provides", "effects", "required_approvals"):
            action[key] = _names(row.get(key, []))
        _require(bool(action["provides"]))
        actions.append(action)
    request["actions"] = actions
    return request


def _assess(module, request):
    claim_data, receipts = request
    claim = module.Claim(**(claim_data | {"required_classes": tuple(
        module.EvidenceClass(kind) for kind in claim_data["required_classes"])}))
    records = tuple(module.EvidenceReceipt(**(row | {
        "kind": module.EvidenceClass(row["kind"]),
        "outcome": module.EvidenceOutcome(row["outcome"])})) for row in receipts)
    expected_digest = _text(module.claim_fingerprint(claim))
    _require(len(expected_digest) == 64 and all(c in "0123456789abcdef" for c in expected_digest))
    result = module.assess_claim(claim, records)
    disposition = result.disposition.value
    _require(type(disposition) is str and disposition in {"SUPPORTED", "UNVERIFIED", "CONTRADICTED"})
    claim_id, subject = _text(result.claim_id), _text(result.subject_ref)
    _require(claim_id == claim_data["claim_id"] and subject == claim_data["subject_ref"])
    digest = _text(result.claim_digest)
    _require(digest == expected_digest)
    ids = {row["receipt_id"] for row in receipts}
    return {"claim_id": claim_id, "subject_ref": subject, "claim_digest": digest,
            "disposition": disposition,
            "admitted_receipt_ids": _output_names(result.admitted_receipt_ids, ids),
            "contradicting_receipt_ids": _output_names(result.contradicting_receipt_ids, ids),
            "reason_codes": _output_names(result.reason_codes, _REASONS)} | _LABELS


def _plan(module, request):
    typed = request | {"actions": tuple(module.Action(**row) for row in request["actions"])}
    result = module.plan_opportunity(module.OpportunityRequest(**typed)).to_dict()
    _fields(result, {"status", "action_ids", "total_cost", "missing_approvals", "blockers",
                     "explored_states", "provenance", "executed", "verified", "evidence_class"})
    status = result["status"]
    _require(type(status) is str and status in {"AVAILABLE", "NEEDS_APPROVAL", "NO_ROUTE", "INCOMPLETE_UNKNOWN"})
    _require(result["executed"] is False and result["verified"] is False
             and type(result["evidence_class"]) is str
             and result["evidence_class"] == "CALLER_SUPPLIED_UNVERIFIED")
    actions = {row["id"]: row for row in request["actions"]}
    route = _output_names(result["action_ids"], set(actions))
    _require(len(route) <= request["max_steps"])
    approvals = {name for action_id in route for name in actions[action_id]["required_approvals"]}
    approvals -= set(request["granted_approvals"])
    missing = _output_names(result["missing_approvals"], approvals)
    _require(set(missing) == approvals)
    if status == "AVAILABLE":
        _require(not missing)
    elif status == "NEEDS_APPROVAL":
        _require(bool(route) and bool(missing))
    elif status == "NO_ROUTE":
        _require(not route and result["total_cost"] is None)
    blockers = _output_names(result["blockers"], _BLOCKERS)
    cost = result["total_cost"]
    if cost is None:
        _require(not route and status in {"NO_ROUTE", "INCOMPLETE_UNKNOWN"})
    else:
        _zero(cost)
    explored = result["explored_states"]
    _require(type(explored) is int and 0 <= explored <= 8192)
    provenance = result["provenance"]
    _require(type(provenance) is dict and set(provenance) == set(route))
    references = {name: _text(provenance[name], 512) for name in route}
    _require(all(references[name] == actions[name]["provenance"] for name in route))
    return {"status": status, "action_ids": route, "total_cost": cost,
            "missing_approvals": missing, "blockers": blockers,
            "explored_states": explored, "provenance": references} | _LABELS


def run_advisory(command, stream):
    """Read and validate before loading either explicitly selected package."""
    try:
        document = _read(stream)
        if command == "claim-assess":
            request = _claim_request(document)
            package, operation = "humility.runtime", _assess
        elif command == "opportunities":
            request = _opportunity_request(document)
            package, operation = "freerowcochkar.opportunities", _plan
        else:
            raise ValueError(_INVALID)
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        raise ValueError(_INVALID) from None
    discarded = _BoundedDiscard()
    # This protects ordinary Python prints only. An installed package can
    # deliberately bypass these streams; it still requires operator trust.
    with redirect_stdout(discarded), redirect_stderr(discarded):
        try:
            module = importlib.import_module(package)
        except ImportError:
            raise ValueError("OPTIONAL_ADVISORY_UNAVAILABLE: " + package) from None
        except (Exception, SystemExit):
            raise ValueError("OPTIONAL_ADVISORY_FAILED: no assessment completed") from None
        try:
            _require(not discarded.exceeded)
            payload = {"schema": "VERA_OPTIONAL_SEMANTIC_ADVISORY_V1", "component": package,
                       "result": operation(module, request)} | _LABELS
            rendered = json.dumps(payload, allow_nan=False, ensure_ascii=True)
            _require(not discarded.exceeded and len(rendered.encode("utf-8")) <= MAX_INPUT_BYTES)
            return payload
        except (Exception, SystemExit):
            raise ValueError("OPTIONAL_ADVISORY_FAILED: no assessment completed") from None
