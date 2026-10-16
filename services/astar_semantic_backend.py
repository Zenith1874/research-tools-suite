"""Use the pinned offline ONNX encoder for an accepted semantic generation."""

import json
from pathlib import Path

from services.astar_onnx_encoder import OnnxBgeEncoder
from services.astar_onnx_validation import digest, validate_receipt
from services.system_memory_gate import memory_headroom

ROOT = Path(__file__).resolve().parents[1]
REVISION = '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a'


def require_encoder_headroom():
    status = memory_headroom()
    if status and (status['commit_available'] < int(1.75 * 2**30)
                   or status['physical_available'] < 2 * 2**30):
        raise MemoryError('ONNX encoding needs 1.75 GiB commit and 2 GiB physical headroom')
    return status


def resolve_verified_backend(metadata):
    if metadata.get('encoder_backend') != 'onnx' or metadata.get('model') != 'BAAI/bge-small-en-v1.5':
        raise ValueError('Automatic updates require the accepted offline ONNX generation')
    saved = metadata.get('backend_validation') or {}
    receipt = Path(saved['receipt_path'])
    if digest(receipt) != saved.get('receipt_sha256'):
        raise ValueError('The accepted ONNX numerical receipt changed')
    configured = metadata.get('onnx_runtime') or {}
    # The existing accepted pack predates explicit runtime-path metadata.
    model = Path(configured.get('model_path') or (
        ROOT / 'backups/abdc_A_extension_20261006'
        / 'embedding_runtime_diagnostics_20261007T211645982539Z/model/onnx/model.onnx'))
    tokenizer = Path(configured.get('tokenizer_dir') or (
        Path.home() / '.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5'
        / 'snapshots' / REVISION))
    validated = validate_receipt(receipt, model, tokenizer)
    return model, tokenizer, validated


class VerifiedOnnxModel:
    """Small adapter for the existing normalized SentenceTransformer call sites."""

    def __init__(self, model, tokenizer, validation, threads=2):
        require_encoder_headroom()
        self.encoder = OnnxBgeEncoder(model, tokenizer, threads=threads)
        self.validation = validation
        self.runtime_paths = {'model_path': str(model), 'tokenizer_dir': str(tokenizer)}

    def encode(self, texts, batch_size=4, normalize_embeddings=True, show_progress_bar=False):
        if not normalize_embeddings:
            raise ValueError('The accepted BGE representation is always L2 normalized')
        single = isinstance(texts, str)
        values = self.encoder.encode([texts] if single else texts,
                                     batch_size=min(4, max(1, int(batch_size))))
        return values[0] if single else values


def load_verified_model(data_dir, threads=2):
    metadata = json.loads((Path(data_dir) / 'astar_emb_meta.json').read_text(encoding='utf-8'))
    model, tokenizer, validation = resolve_verified_backend(metadata)
    return VerifiedOnnxModel(model, tokenizer, validation, threads=threads)
