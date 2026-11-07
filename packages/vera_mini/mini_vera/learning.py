"""Small, offline, advisory-only text intent learner.

This is a trainable hashed-feature multinomial logistic regression model, **not**
a neural network or an authorization engine. Its weights start at zero. Training
text never enters checkpoints. The redaction guard is deliberately conservative;
callers remain responsible for obtaining consent and excluding private data.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import tempfile
from pathlib import Path


LABELS = ("challenge", "support", "probe", "direct", "identity", "unknown")
_TOKENS = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PRIVATE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:password|api[_ -]?key|"
    r"secret[_ -]?key|access[_ -]?token|bearer)\s*[:=]\s*\S+)", re.I
)
_SCHEMA = "mini-vera-intent-logreg-v1"
_MAX_CHECKPOINT = 4_000_000


def _validated_text(text: str, *, for_training: bool) -> str:
    if not isinstance(text, str) or not text.strip() or len(text) > 2048:
        raise ValueError("text must be a nonempty string of at most 2048 characters")
    if for_training and (_EMAIL.search(text) or _PRIVATE.search(text)):
        raise ValueError("potential personal or secret material cannot be trained on")
    return text


class IntentLearner:
    """CPU-only classifier. Predictions are suggestions, never permissions.

    ``fit`` accepts a sequence of ``(text, label)`` pairs; ``predict`` returns
    ``label``, ``confidence``, ``probabilities``, and ``advisory_only``. An
    uncertain prediction resolves to ``unknown``. All labels are fixed and
    untrusted training labels outside this vocabulary are rejected.
    """

    def __init__(self, dimensions: int = 512, seed: int = 7,
                 min_confidence: float = 0.36) -> None:
        if type(dimensions) is not int or not 64 <= dimensions <= 2048:
            raise ValueError("dimensions must be an integer from 64 to 2048")
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("seed must be a nonnegative 32-bit integer")
        if not isinstance(min_confidence, (float, int)) or isinstance(min_confidence, bool) or not math.isfinite(min_confidence) or not 0 < min_confidence < 1:
            raise ValueError("min_confidence must be finite and between zero and one")
        self.dimensions = dimensions
        self.seed = seed
        self.min_confidence = float(min_confidence)
        self.weights = [[0.0] * dimensions for _ in LABELS]
        self.bias = [0.0] * len(LABELS)
        self.trained_samples = 0
        self.steps = 0

    def _features(self, text: str) -> dict[int, float]:
        tokens = _TOKENS.findall(text.lower())[:256]
        terms = ["u:" + t for t in tokens]
        terms.extend("b:" + a + "_" + b for a, b in zip(tokens, tokens[1:]))
        counts: dict[int, float] = {}
        for term in terms:
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "big")
            index, sign = raw % self.dimensions, (1 if raw & (1 << 63) else -1)
            counts[index] = counts.get(index, 0.0) + sign
        norm = math.sqrt(sum(x*x for x in counts.values())) or 1.0
        return {k: v / norm for k, v in counts.items() if v}

    def _probabilities(self, features: dict[int, float]) -> list[float]:
        logits = [b + sum(row[k] * v for k, v in features.items())
                  for b, row in zip(self.bias, self.weights)]
        high = max(logits)
        exp = [math.exp(z - high) for z in logits]
        total = sum(exp)
        return [x / total for x in exp]

    def fit(self, examples: list[tuple[str, str]], *, epochs: int = 50,
            learning_rate: float = 0.25) -> dict[str, float | int]:
        """Train from scratch with deterministic shuffled SGD; no input retained.

        Re-fitting starts at zero, so runs are reproducible rather than silently
        accumulating unrelated or potentially poisoned training histories.
        """
        if not isinstance(examples, (list, tuple)) or not 1 <= len(examples) <= 2000:
            raise ValueError("examples must contain 1 to 2000 (text, label) pairs")
        if type(epochs) is not int or not 1 <= epochs <= 200:
            raise ValueError("epochs must be an integer from 1 to 200")
        if not isinstance(learning_rate, (float, int)) or isinstance(learning_rate, bool) or not math.isfinite(learning_rate) or not 0 < learning_rate <= 1:
            raise ValueError("learning_rate must be finite, positive, and at most 1")
        prepared: list[tuple[dict[int, float], int]] = []
        for example in examples:
            if not isinstance(example, (tuple, list)) or len(example) != 2:
                raise ValueError("every example must be a (text, label) pair")
            text, label = example
            _validated_text(text, for_training=True)
            if type(label) is not str or label not in LABELS:
                raise ValueError("unrecognized training label")
            prepared.append((self._features(text), LABELS.index(label)))
        self.weights = [[0.0] * self.dimensions for _ in LABELS]
        self.bias = [0.0] * len(LABELS)
        self.trained_samples = len(prepared)
        self.steps = 0
        rng = random.Random(self.seed)
        order = list(range(len(prepared)))
        loss = 0.0
        for _ in range(epochs):
            rng.shuffle(order)
            loss = 0.0
            for item in order:
                features, target = prepared[item]
                probabilities = self._probabilities(features)
                loss -= math.log(max(probabilities[target], 1e-15))
                for cls in range(len(LABELS)):
                    grad = (1.0 if cls == target else 0.0) - probabilities[cls]
                    update = learning_rate * grad
                    self.bias[cls] += update
                    for k, value in features.items():
                        self.weights[cls][k] += update * value
                self.steps += 1
        return {"samples": len(prepared), "epochs": epochs,
                "mean_training_loss": loss / len(prepared)}

    def predict(self, text: str) -> dict[str, object]:
        _validated_text(text, for_training=False)
        if not self.trained_samples:
            return {"label": "unknown", "confidence": 0.0,
                    "probabilities": {label: 0.0 for label in LABELS},
                    "advisory_only": True}
        probabilities = self._probabilities(self._features(text))
        index = max(range(len(LABELS)), key=probabilities.__getitem__)
        label = LABELS[index] if probabilities[index] >= self.min_confidence else "unknown"
        return {"label": label, "confidence": probabilities[index],
                "probabilities": dict(zip(LABELS, probabilities)),
                "advisory_only": True}

    def to_dict(self) -> dict[str, object]:
        return {"schema": _SCHEMA, "labels": list(LABELS),
                "dimensions": self.dimensions, "seed": self.seed,
                "min_confidence": self.min_confidence,
                "weights": self.weights, "bias": self.bias,
                "trained_samples": self.trained_samples, "steps": self.steps}

    @classmethod
    def from_dict(cls, data: object) -> "IntentLearner":
        required = {"schema", "labels", "dimensions", "seed", "min_confidence",
                    "weights", "bias", "trained_samples", "steps"}
        if type(data) is not dict or set(data) != required or data["schema"] != _SCHEMA or data["labels"] != list(LABELS):
            raise ValueError("invalid checkpoint schema or labels")
        model = cls(data["dimensions"], data["seed"], data["min_confidence"])
        for name in ("trained_samples", "steps"):
            value = data[name]
            if type(value) is not int or not 0 <= value <= 400_000:
                raise ValueError("invalid checkpoint training counters")
        if data["steps"] < data["trained_samples"] or (data["steps"] == 0) != (data["trained_samples"] == 0):
            raise ValueError("inconsistent checkpoint training counters")
        weights, bias = data["weights"], data["bias"]
        if type(weights) is not list or len(weights) != len(LABELS) or type(bias) is not list or len(bias) != len(LABELS):
            raise ValueError("invalid checkpoint matrix shape")
        if any(type(row) is not list or len(row) != model.dimensions for row in weights):
            raise ValueError("invalid checkpoint matrix shape")
        values = [v for row in weights for v in row] + bias
        if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in values):
            raise ValueError("invalid checkpoint weight value")
        model.weights = [[float(v) for v in row] for row in weights]
        model.bias = [float(v) for v in bias]
        model.trained_samples = data["trained_samples"]
        model.steps = data["steps"]
        return model

    def save(self, path: str | os.PathLike[str]) -> None:
        """Atomically write a small JSON checkpoint containing parameters only."""
        destination = Path(path)
        if not destination.parent.is_dir():
            raise ValueError("checkpoint parent directory does not exist")
        fd, temporary = tempfile.mkstemp(prefix=".mini-vera-", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.to_dict(), stream, separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "IntentLearner":
        destination = Path(path)
        if not destination.is_file() or destination.stat().st_size > _MAX_CHECKPOINT:
            raise ValueError("checkpoint missing or too large")
        try:
            with destination.open("r", encoding="utf-8") as stream:
                data = json.load(stream, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON number")))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("malformed checkpoint") from exc
        return cls.from_dict(data)


MiniVeraLearner = IntentLearner
