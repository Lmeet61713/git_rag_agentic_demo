import hashlib
import math
import re


class HashEmbedding:
    """Deterministic local fallback embedding used when no ONNX model is configured."""

    dim = 64

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        for token in tokens or [text]:
            index = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self.dim
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


def get_embedding():
    # TODO: load a local ONNX model from EMBEDDING_MODEL_PATH when available.
    return HashEmbedding()
