import hashlib
import math
import re
from pathlib import Path

import jieba


def chinese_tokens(text: str) -> list[str]:
    return [token for token in jieba.cut_for_search(text.lower()) if len(token.strip()) > 1]


class HashEmbedding:
    """Deterministic local fallback embedding used when no ONNX model is configured."""

    dim = 64

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = chinese_tokens(text) or re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        for token in tokens or [text]:
            index = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self.dim
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


class OnnxEmbedding:
    """Mean-pooled multilingual ONNX embedding used for local semantic search."""

    def __init__(self, model_path: Path | str, tokenizer_path: Path | str, dim: int = 512):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.dim = dim
        self.np = np
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(self._embed_batch(texts[start : start + batch_size]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        np = self.np
        if not texts:
            return []
        encodings = self.tokenizer.encode_batch(texts)
        input_ids = np.array([item.ids for item in encodings], dtype=np.int64)
        attention_mask = np.array([item.attention_mask for item in encodings], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids)
        outputs = self.session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )[0]
        mask = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
        summed = np.sum(outputs * mask, axis=1)
        counts = np.maximum(np.sum(mask, axis=1), 1e-9)
        vectors = summed / counts
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-9)
        return [vector.tolist() for vector in vectors]


def _default_model_paths() -> tuple[Path, Path] | None:
    model_dir = Path(__file__).resolve().parents[3] / "data" / "models" / "bge-small-zh-v1.5"
    model = model_dir / "onnx" / "model.onnx"
    tokenizer = model_dir / "tokenizer.json"
    if model.exists() and tokenizer.exists():
        return model, tokenizer
    return None


def get_embedding():
    from backend.app.config import get_settings

    settings = get_settings()
    model_path = settings.embedding_model_path or ""
    if not model_path:
        defaults = _default_model_paths()
        if defaults:
            model_path, tokenizer_path = defaults
        else:
            return HashEmbedding()
    else:
        model = Path(model_path)
        tokenizer_path = model.parent / "tokenizer.json"
        if not tokenizer_path.exists():
            tokenizer_path = model.parents[1] / "tokenizer.json"
        if not tokenizer_path.exists() or not model.exists():
            return HashEmbedding()
    try:
        return OnnxEmbedding(model_path, tokenizer_path)
    except Exception:
        return HashEmbedding()
