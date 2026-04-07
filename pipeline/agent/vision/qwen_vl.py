"""
Qwen2.5-VL – Vision-language model for UI element grounding.

Supports two sizes:
  - Qwen2.5-VL-3B-Instruct  (~7GB VRAM, ~1s/image)  — good for most cases
  - Qwen2.5-VL-7B-Instruct  (~16GB VRAM, ~2s/image)  — more accurate

First-class HuggingFace model — no trust_remote_code needed, actively maintained.

Install: pip install torch transformers accelerate qwen-vl-utils Pillow
Model:   auto-downloaded from HuggingFace on first use.
"""

from __future__ import annotations
import base64
import io
import json
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_model = None
_processor = None
_loaded_model_id = None

# Model variants by size
MODEL_VARIANTS = {
    "3b": "Qwen/Qwen2.5-VL-3B-Instruct",
    "7b": "Qwen/Qwen2.5-VL-7B-Instruct",
}


def _load_model(device: str = "auto", model_size: str = "3b"):
    """Load Qwen2.5-VL model (cached across calls)."""
    global _model, _processor, _loaded_model_id

    model_id = MODEL_VARIANTS.get(model_size, MODEL_VARIANTS["3b"])

    # Already loaded this exact model
    if _model is not None and _loaded_model_id == model_id:
        return

    # Different model requested — unload first
    if _model is not None:
        unload()

    import torch
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info("Loading %s (%s)…", model_id, device)

    _processor = AutoProcessor.from_pretrained(model_id)
    _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        device_map=device if device == "cuda" else None,
    )
    if device == "cpu":
        _model = _model.to(device)

    _loaded_model_id = model_id
    logger.info("Qwen2.5-VL loaded: %s on %s", model_id, device)


def _parse_coordinates(text: str, img_w: int, img_h: int) -> Optional[Tuple[int, int]]:
    """
    Parse Qwen2.5-VL output for coordinates.

    Handles multiple formats:
    - JSON: {"x": 123, "y": 456}
    - Parentheses: (123, 456)
    - Bounding box: [x1, y1, x2, y2]
    - Normalized values (0-1000 range)
    """
    # Try JSON
    try:
        json_match = re.search(r'\{[^}]*\}', text)
        if json_match:
            data = json.loads(json_match.group())
            if "x" in data and "y" in data:
                x, y = int(data["x"]), int(data["y"])
                if x > img_w or y > img_h:
                    x = int(x / 1000 * img_w)
                    y = int(y / 1000 * img_h)
                return (x, y)
    except (json.JSONDecodeError, ValueError):
        pass

    # Try parentheses: (x, y)
    paren = re.search(r'\((\d+)\s*,\s*(\d+)\)', text)
    if paren:
        x, y = int(paren.group(1)), int(paren.group(2))
        if x > img_w or y > img_h:
            x = int(x / 1000 * img_w)
            y = int(y / 1000 * img_h)
        return (x, y)

    # Try bounding box: [x1, y1, x2, y2]
    bbox = re.search(r'\[(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\]', text)
    if bbox:
        x1, y1, x2, y2 = [int(g) for g in bbox.groups()]
        if x2 > img_w or y2 > img_h:
            x1 = int(x1 / 1000 * img_w)
            y1 = int(y1 / 1000 * img_h)
            x2 = int(x2 / 1000 * img_w)
            y2 = int(y2 / 1000 * img_h)
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))

    # Try bare numbers
    nums = re.findall(r'(\d+)', text)
    if len(nums) >= 2:
        x, y = int(nums[0]), int(nums[1])
        if 0 < x < img_w * 2 and 0 < y < img_h * 2:
            if x > img_w or y > img_h:
                x = int(x / 1000 * img_w)
                y = int(y / 1000 * img_h)
            return (x, y)

    return None


def locate(
    image_bytes: bytes,
    device: str = "auto",
    model_size: str = "3b",
) -> Optional[Tuple[int, int]]:
    """
    Find the Cloudflare checkbox in a screenshot using Qwen2.5-VL.

    Parameters
    ----------
    image_bytes : bytes
        PNG screenshot.
    device : str
        "cuda", "cpu", or "auto".
    model_size : str
        "3b" or "7b".

    Returns
    -------
    (x, y) pixel coordinates of the checkbox center, or None.
    """
    from PIL import Image

    _load_model(device, model_size)

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = image.size

    # Resize large screenshots to avoid CUDA overflow in the 3B model.
    # Keep track of scale to convert coordinates back to original size.
    MAX_DIM = 1280
    scale = 1.0
    if max(orig_w, orig_h) > MAX_DIM:
        scale = max(orig_w, orig_h) / MAX_DIM
        new_w = int(orig_w / scale)
        new_h = int(orig_h / scale)
        image = image.resize((new_w, new_h), Image.LANCZOS)
        logger.debug("Resized screenshot %dx%d → %dx%d (scale=%.2f)",
                      orig_w, orig_h, new_w, new_h, scale)

    img_w, img_h = image.size

    # Re-encode the (possibly resized) image
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    prompt = (
        "This is a screenshot of a computer screen showing a Cloudflare verification page "
        "in a web browser. There is a widget with a square checkbox on the LEFT side and "
        "a Cloudflare logo on the RIGHT side. "
        "I need to click the SQUARE CHECKBOX on the LEFT, NOT the Cloudflare logo. "
        "Return the pixel coordinates of the EXACT CENTER of the square checkbox. "
        "Return ONLY JSON: {\"x\": ..., \"y\": ...}. "
        "Image dimensions: %d x %d pixels." % (img_w, img_h)
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": f"data:image/png;base64,{b64}"},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    try:
        text = _processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        from qwen_vl_utils import process_vision_info
        image_inputs, video_inputs = process_vision_info(messages)

        inputs = _processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        dev = next(_model.parameters()).device
        inputs = inputs.to(dev)

        import torch
        with torch.no_grad():
            output_ids = _model.generate(**inputs, max_new_tokens=128)

        generated = output_ids[:, inputs.input_ids.shape[1]:]
        response = _processor.batch_decode(generated, skip_special_tokens=True)[0]

        logger.debug("Qwen2.5-VL response: %s", response)

        result = _parse_coordinates(response, img_w, img_h)
        if result:
            # Scale coordinates back to original screenshot size
            rx = int(result[0] * scale)
            ry = int(result[1] * scale)
            result = (rx, ry)
            logger.info("Qwen2.5-VL found checkbox at (%d, %d) [model coords: scale=%.2f]",
                        result[0], result[1], scale)
        else:
            logger.info("Qwen2.5-VL could not parse coordinates from: %s", response)
        return result

    except Exception as exc:
        logger.warning("Qwen2.5-VL inference failed: %s", exc)
        # If CUDA error, the device is in a bad state — must reload model
        if "CUDA" in str(exc) or "cuda" in str(exc):
            logger.info("CUDA error detected, reloading model on next attempt…")
            unload()
        return None


def unload():
    """Free model from memory."""
    global _model, _processor, _loaded_model_id
    if _model is not None:
        del _model, _processor
        _model = _processor = None
        _loaded_model_id = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("Qwen2.5-VL unloaded")
