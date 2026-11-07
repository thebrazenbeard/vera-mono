"""Train Mini-Vera's tiny advisory intent model from public authored examples.

This script is intentionally separate from inference: training is an explicit
operator action, never triggered by a retrieved document or a conversation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mini_vera.learning import IntentLearner, LABELS  # noqa: E402
from mini_vera.dialogue import respond  # noqa: E402


def load_split(path: Path) -> tuple[list[tuple[str, str]], set[str], str]:
    blob = path.read_bytes()
    if len(blob) > 1_000_000:
        raise ValueError(f"dataset split {path.name} exceeds maximum size")
    rows = []
    groups = set()
    seen_text = set()
    for lineno, line in enumerate(blob.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if type(item) is not dict or set(item) != {"text", "label", "group"}:
            raise ValueError(f"invalid record schema at {path.name}:{lineno}")
        text, label, group = item["text"], item["label"], item["group"]
        if type(text) is not str or not text.strip() or len(text) > 512 \
                or type(label) is not str or label not in LABELS \
                or type(group) is not str or not group.strip():
            raise ValueError(f"invalid record values at {path.name}:{lineno}")
        key = " ".join(text.casefold().split())
        if key in seen_text:
            raise ValueError(f"duplicate example in {path.name}")
        seen_text.add(key)
        groups.add(group)
        rows.append((text, label))
    if not rows:
        raise ValueError(f"empty split: {path.name}")
    return rows, groups, hashlib.sha256(blob).hexdigest()


def evaluate(model: IntentLearner, records: list[tuple[str, str]]) -> dict:
    correct = 0
    confusion = {label: Counter() for label in LABELS}
    for text, label in records:
        output = model.predict(text)
        guess = output["label"]
        confusion[label][guess] += 1
        correct += int(guess == label)
    return {"examples": len(records), "correct": correct,
            "accuracy": round(correct / len(records), 4),
            "confusion": {label: dict(confusion[label]) for label in LABELS}}


def run(*, data: Path, output: Path, metrics: Path, seed: int = 7,
        epochs: int = 50, min_margin: float = 0.05) -> dict:
    splits = {}
    for name in ("train", "validation", "test"):
        splits[name] = load_split(data / f"{name}.jsonl")
    for first, second in (("train", "validation"), ("train", "test"),
                          ("validation", "test")):
        if splits[first][1] & splits[second][1]:
            raise ValueError(f"scenario group leakage across {first}/{second}")
        texts_a = {" ".join(x.casefold().split()) for x, _ in splits[first][0]}
        texts_b = {" ".join(x.casefold().split()) for x, _ in splits[second][0]}
        if texts_a & texts_b:
            raise ValueError(f"example text leakage across {first}/{second}")
    model = IntentLearner(seed=seed)
    training = model.fit(splits["train"][0], epochs=epochs)
    stats = {name: evaluate(model, records[0]) for name, records in splits.items()}
    counts = Counter(label for _, label in splits["train"][0])
    majority = counts.most_common(1)[0][0]
    baseline = sum(label == majority for _, label in splits["test"][0]) / len(splits["test"][0])
    baseline_intent_map = {
        "self_identity": "identity", "runtime_provenance": "identity",
        "memory_boundary": "identity", "emotional_support": "support",
        "urgent_support": "support", "unknown": "unknown",
    }
    frozen_correct = 0
    for prompt, expected in splits["test"][0]:
        result_before_learning = respond(prompt, facts=[])
        route = baseline_intent_map.get(result_before_learning["intents"][0], "unknown")
        frozen_correct += int(route == expected)
    result = {
        "schema": "mini-vera-intent-training-receipt-v1",
        "model": "hashed-feature-multinomial-logistic-regression (non-neural)",
        "training": training, "seed": seed,
        "data_sha256": {name: item[2] for name, item in splits.items()},
        "heldout_scenario_groups_disjoint": True,
        "majority_baseline_label": majority,
        "majority_baseline_accuracy": round(baseline, 4),
        "frozen_rule_baseline_accuracy": round(
            frozen_correct / len(splits["test"][0]), 4),
        "frozen_rule_baseline_correct": frozen_correct,
        "metrics": stats,
        "scope": "intent routing only; no demonstrated generative-language learning",
    }
    # A measured gain is necessary for any assertion that the learner improved
    # over a trivial majority-class baseline on the held-out set.
    if stats["test"]["accuracy"] < baseline + min_margin:
        raise RuntimeError(
            "held-out accuracy did not beat majority baseline by required margin; "
            f"model={stats['test']['accuracy']:.3f}, baseline={baseline:.3f}")
    if not output.parent.is_dir() or not metrics.parent.is_dir():
        raise ValueError("destination parent directories must already exist")
    output.write_text(json.dumps(model.to_dict(), sort_keys=True,
                                 separators=(",", ":")) + "\n", encoding="utf-8")
    result["checkpoint_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    metrics.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--data", type=Path, default=ROOT / "data")
    cli.add_argument("--output", type=Path,
                     default=ROOT / "mini_vera/resources/INTENT_POLICY_V1.json")
    cli.add_argument("--metrics", type=Path, default=ROOT / "data/training_receipt_v1.json")
    cli.add_argument("--seed", type=int, default=7)
    cli.add_argument("--epochs", type=int, default=50)
    args = cli.parse_args()
    result = run(data=args.data, output=args.output, metrics=args.metrics,
                 seed=args.seed, epochs=args.epochs)
    print(json.dumps({"test": result["metrics"]["test"],
                      "majority_baseline": result["majority_baseline_accuracy"],
                      "checkpoint_sha256": result["checkpoint_sha256"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
