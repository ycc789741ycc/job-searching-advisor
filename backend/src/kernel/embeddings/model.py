"""Local embeddings and clustering.

This is plain computation, so the platform pays for it — the user's key is
spent only on generative work (domain decision 7). The model is loaded lazily
and once, because importing it costs far more than calling it.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sentence_transformers import SentenceTransformer

_lock = threading.Lock()
_model: SentenceTransformer | None = None
_model_name: str | None = None

EMBEDDING_DIMENSIONS = 384  # all-MiniLM-L6-v2


def load_model(model_name: str) -> SentenceTransformer:
    global _model, _model_name
    with _lock:
        if _model is None or _model_name != model_name:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(model_name)
            _model_name = model_name
        return _model


def embed(texts: list[str], *, model_name: str) -> list[list[float]]:
    """Embed a batch of posting texts. Order is preserved."""
    if not texts:
        return []
    model = load_model(model_name)
    vectors: Any = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [[float(x) for x in row] for row in vectors]
