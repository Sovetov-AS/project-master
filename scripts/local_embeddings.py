"""Optional local FastEmbed adapter. No document text leaves this process.

Model download requires explicit PM_EMBEDDING_DOWNLOAD=1; subsequent runs use
only the configured local cache. Install fastembed separately, never at runtime.
"""
import math
import os
from pathlib import Path
_MODEL = None
MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'

def identity(): return MODEL_NAME + ':fastembed0.7.4:mean:384:paragraph1600-v1'

def embed(texts):
    global _MODEL
    if _MODEL is None:
        from importlib.metadata import version
        if version('fastembed') != '0.7.4': raise RuntimeError('install supported fastembed==0.7.4')
        from fastembed import TextEmbedding
        cache = os.environ.get('PM_EMBEDDING_CACHE')
        if not cache: raise RuntimeError('set PM_EMBEDDING_CACHE to an explicit local model directory')
        _MODEL = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(Path(cache).resolve()), local_files_only=os.environ.get('PM_EMBEDDING_DOWNLOAD') != '1')
    vectors = [[float(x) for x in v] for v in _MODEL.embed(texts)]
    if len(vectors) != len(texts) or any(len(v) != 384 or not all(math.isfinite(x) for x in v) for v in vectors):
        raise ValueError('invalid local embedding output')
    return vectors

def cosine(a, b):
    if len(a) != len(b) or not a or not all(math.isfinite(x) for x in a+b): raise ValueError('incompatible vectors')
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x,y in zip(a,b)) / norm if norm else 0.0
