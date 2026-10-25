"""Safe CLI: corpus prep and separately gated offline-only LoRA experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapter_prep import build_plan, write_private_splits
from .lora_runner import plan_local_training, train_local_adapter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Vera adapter preparation and gated local LoRA")
    parser.add_argument("action", choices=("plan", "prepare", "train-plan", "train"))
    parser.add_argument("manifest", type=Path, help="Absolute path to private operator-reviewed manifest")
    parser.add_argument("output", nargs="?", type=Path, help="New private output directory (prepare/train)")
    parser.add_argument("--model-dir", type=Path, help="Local verified full-precision model snapshot (train only)")
    parser.add_argument("--approval", help="Exact preflight-bound weight-update approval (train only)")
    parser.add_argument("--execute", action="store_true", help="Opt-in to weight update (train only)")
    parser.add_argument("--steps", type=int, default=1, help="Bounded optimizer steps, 1..32")
    args = parser.parse_args(argv)
    is_training = args.action in ("train-plan", "train")
    if (args.action != "plan") != (args.output is not None):
        parser.error("prepare/train-plan/train require output; plan forbids output")
    if is_training != (args.model_dir is not None):
        parser.error("train-plan/train require --model-dir; preparation forbids it")
    if args.action != "train" and (args.approval or args.execute):
        parser.error("--approval/--execute only available with train")
    if not is_training and args.steps != 1:
        parser.error("--steps only available with train-plan/train")
    if args.action == "train" and not args.execute:
        parser.error("train requires --execute and exact --approval")
    try:
        if is_training:
            if args.action == "train-plan":
                plan = plan_local_training(args.manifest, args.model_dir, args.output,
                                           steps=args.steps)
            else:
                plan = train_local_adapter(args.manifest, args.model_dir, args.output,
                                           approval=args.approval or "", execute=args.execute,
                                           steps=args.steps)
            print(json.dumps({
                "status": "PREFLIGHT_ONLY_NOT_TRAINED" if args.action == "train-plan" else "TRAINED_ADAPTER_UNQUALIFIED_UNEVALUATED_NOT_ACTIVATED",
                "manifest_sha256": plan.manifest_sha256,
                "model_snapshot_sha256": plan.model_snapshot_sha256,
                "training_count": plan.train_examples,
                "heldout_count": plan.heldout_examples,
                "optimizer_steps": plan.optimizer_steps,
                "recipe_sha256": plan.recipe_sha256,
                **({"exact_approval_to_copy_for_train": plan.weight_update_approval} if args.action == "train-plan" else {}),
            }, sort_keys=True))
            return 0
        plan = write_private_splits(args.manifest, args.output) if args.output else build_plan(args.manifest)
    except OSError:
        # OS errors commonly embed absolute paths to private manifests, model
        # checkpoints and datasets. Never disclose them through CLI logs.
        print(f"{'TRAINING_HOLD' if is_training else 'PREPARATION_HOLD'}: private local file operation failed",
              file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"{'TRAINING_HOLD' if is_training else 'PREPARATION_HOLD'}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": "PREPARED_ONLY_NOT_TRAINED_OR_QUALIFIED",
        "manifest_sha256": plan.manifest_sha256,
        "base_model_binding_sha256": plan.base_model_binding_sha256,
        "corpus_sha256": plan.corpus_sha256,
        "training_count": plan.training_count,
        "evaluation_count": plan.evaluation_count,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
