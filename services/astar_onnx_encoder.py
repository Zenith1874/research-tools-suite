"""Offline FP32 BGE CLS encoder using an explicitly verified ONNX artifact."""

import json
from pathlib import Path


def normalized_cls(token_embeddings):
    import numpy as np
    values = np.asarray(token_embeddings, dtype=np.float32)
    if values.ndim != 3 or values.shape[2] != 384 or not values.shape[1]:
        raise ValueError('Expected BGE token embeddings shaped batch x tokens x 384')
    cls = values[:, 0, :]
    norm = np.linalg.norm(cls, axis=1, keepdims=True)
    if not np.isfinite(cls).all() or not np.isfinite(norm).all() or (norm <= 0).any():
        raise ValueError('Invalid BGE CLS vector')
    return np.asarray(cls / norm, dtype=np.float32)


class OnnxBgeEncoder:
    def __init__(self, onnx_path, tokenizer_dir, threads=1):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        directory = Path(tokenizer_dir)
        pooling = json.loads((directory / '1_Pooling/config.json').read_text(encoding='utf-8'))
        if (pooling.get('word_embedding_dimension') != 384 or not pooling.get('pooling_mode_cls_token')
                or pooling.get('pooling_mode_mean_tokens') or pooling.get('pooling_mode_max_tokens')):
            raise ValueError('This runtime requires the verified 384-dimensional CLS pooling configuration')
        config = json.loads((directory / 'sentence_bert_config.json').read_text(encoding='utf-8'))
        self.maximum_tokens = config['max_seq_length']
        self.tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=self.maximum_tokens, direction='right')
        self.tokenizer.enable_padding(pad_id=0, pad_type_id=0, pad_token='[PAD]', direction='right')
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(onnx_path), sess_options=options, providers=['CPUExecutionProvider'])
        self.input_names = {item.name for item in self.session.get_inputs()}
        if not {'input_ids', 'attention_mask'} <= self.input_names:
            raise ValueError('ONNX input schema differs from the pinned BGE model')
        self.output_name = next((item.name for item in self.session.get_outputs()
                                 if item.name == 'last_hidden_state'), None)
        if self.output_name is None:
            raise ValueError('The ONNX graph must expose its actual last hidden state for CLS pooling')

    def encode(self, texts, batch_size=4):
        import numpy as np
        from services.system_memory_gate import require_headroom
        vectors = []
        for first in range(0, len(texts), batch_size):
            require_headroom()
            encoded = self.tokenizer.encode_batch([text.strip() for text in texts[first:first + batch_size]])
            data = {'input_ids': np.asarray([item.ids for item in encoded], dtype=np.int64),
                    'attention_mask': np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
                    'token_type_ids': np.asarray([item.type_ids for item in encoded], dtype=np.int64)}
            values = self.session.run([self.output_name], {key: value for key, value in data.items()
                                                         if key in self.input_names})[0]
            vectors.append(normalized_cls(values))
        return np.vstack(vectors) if vectors else np.empty((0, 384), dtype=np.float32)
