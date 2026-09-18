from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError


def _resize(image: np.ndarray, width: int, height: int) -> np.ndarray:
    source_h, source_w = image.shape[:2]
    x = (np.arange(width, dtype=np.float64) + .5) * source_w / width - .5
    y = (np.arange(height, dtype=np.float64) + .5) * source_h / height - .5
    x0, y0 = np.clip(np.floor(x).astype(int), 0, source_w - 1), np.clip(np.floor(y).astype(int), 0, source_h - 1)
    x1, y1 = np.clip(x0 + 1, 0, source_w - 1), np.clip(y0 + 1, 0, source_h - 1)
    ax, ay = (x - np.floor(x)).astype(np.float32), (y - np.floor(y)).astype(np.float32)
    top = image[y0[:, None], x0] * (1 - ax)[None, :, None] + image[y0[:, None], x1] * ax[None, :, None]
    bottom = image[y1[:, None], x0] * (1 - ax)[None, :, None] + image[y1[:, None], x1] * ax[None, :, None]
    return top * (1 - ay)[:, None, None] + bottom * ay[:, None, None]


def _preprocess(content: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.seek(0)
            pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("验证码图片无法读取") from error
    return np.ascontiguousarray((_resize(pixels, 130, 52).swapaxes(0, 1) / 255)[None])


def _decode(logits: np.ndarray) -> list[int]:
    values = np.asarray(logits, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] < 2 or not np.isfinite(values).all():
        raise ValueError("ONNX 验证码模型输出无效")
    prefix: list[int] = []
    blank, label = 0.0, -np.inf
    for row in values:
        maximum = row.max()
        row = row - maximum - np.log(np.exp(row - maximum).sum())
        total = np.logaddexp(blank, label)
        same = label + row[prefix[-1]] if prefix else -np.inf
        next_blank = total + row[-1]
        best, winner = np.logaddexp(next_blank, same), None
        winner_probability = -np.inf
        for candidate_label in range(len(row) - 1):
            candidate = (blank if prefix and candidate_label == prefix[-1] else total) + row[candidate_label]
            if candidate > best:
                best, winner, winner_probability = candidate, candidate_label, candidate
        if winner is None:
            blank, label = next_blank, same
        else:
            prefix.append(winner)
            blank, label = -np.inf, winner_probability
    return prefix


class Recognizer:
    def __init__(self, model_dir: Path):
        import onnxruntime as ort
        manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
        model = model_dir / "captcha.onnx"
        if hashlib.sha256(model.read_bytes()).hexdigest() != manifest["sha256"]:
            raise ValueError("ONNX 模型校验失败")
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
        self.alphabet = manifest["alphabet"]
        self.input_name = manifest["input"]
        self.output_name = manifest["output"]

    def recognize(self, content: bytes) -> str:
        logits = self.session.run([self.output_name], {self.input_name: _preprocess(content)})[0]
        # Exported model shape is time × batch × class. The CLI recognizes one
        # captcha at a time, so CTC must receive every time step of batch zero.
        return "".join(self.alphabet[index] for index in _decode(logits[:, 0, :]))
