"""Optional local semantic ranking for keyword search.

Absent the ``memory-fabric[semantic]`` extra (or when
``MEMORY_FABRIC_SEMANTIC=0``), every helper here reports unavailable and
search stays lexical. Tests inject a backend via ``set_embedder`` so CI
never downloads a model.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

# ``embed_texts(texts) -> one vector per text``. Empty list on failure.
Embedder = Callable[[Sequence[str]], list[list[float]]]

_embedder: Embedder | None = None
_fastembed_checked = False
_fastembed_model: object | None = None


def set_embedder(embedder: Embedder | None) -> None:
    """Install or clear a process-local embedder (tests / custom backends)."""
    global _embedder
    _embedder = embedder


def semantic_available() -> bool:
    if _embedder is not None:
        return True
    return _load_fastembed() is not None


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Return one embedding per input string, or ``[]`` on failure."""
    if not texts:
        return []
    if _embedder is not None:
        try:
            vectors = _embedder(texts)
        except Exception:  # noqa: BLE001 - semantic is best-effort.
            return []
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            return []
        return [list(map(float, row)) for row in vectors]
    model = _load_fastembed()
    if model is None:
        return []
    try:
        # fastembed TextEmbedding.embed yields numpy-compatible rows.
        raw = list(model.embed(list(texts)))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - degrade to lexical.
        return []
    if len(raw) != len(texts):
        return []
    out: list[list[float]] = []
    for row in raw:
        out.append([float(x) for x in row])
    return out


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def blend_scores(
    lexical: float,
    cosine: float,
    *,
    lexical_weight: float = 0.7,
) -> float:
    """Blend a BM25-ish score with cosine in ``[0, 1]``.

    Cosine is clamped to ``[0, 1]``. Lexical is min-max normalized only when
    the caller already placed scores on a comparable scale; here we treat a
    non-positive lexical as pure cosine (paraphrase miss) and otherwise keep
    lexical dominant via ``lexical_weight``.
    """
    cos = max(0.0, min(1.0, cosine))
    if lexical <= 0:
        return cos
    weight = max(0.0, min(1.0, lexical_weight))
    # Scale cosine into the lexical magnitude so a 0.9 cosine cannot bury a
    # strong BM25 hit when lexical_weight is high.
    return weight * lexical + (1.0 - weight) * (cos * max(lexical, 1.0))


def _load_fastembed() -> object | None:
    global _fastembed_checked, _fastembed_model
    if _fastembed_checked:
        return _fastembed_model
    _fastembed_checked = True
    try:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]
    except ImportError:
        _fastembed_model = None
        return None
    try:
        # Small default; callers that need another model set MEMORY_FABRIC_EMBED_MODEL.
        import os

        model_name = (
            os.environ.get("MEMORY_FABRIC_EMBED_MODEL") or "sentence-transformers/all-MiniLM-L6-v2"
        )
        _fastembed_model = TextEmbedding(model_name=model_name)
    except Exception:  # noqa: BLE001 - optional dependency may fail to init.
        _fastembed_model = None
    return _fastembed_model
