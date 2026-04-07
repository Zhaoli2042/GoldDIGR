"""
Florence-2 – Fast visual grounding model (~2GB VRAM, sub-second).

Microsoft's Florence-2 is specifically trained for visual grounding tasks
like "point to the checkbox." It returns bounding box coordinates natively.

Install: pip install torch transformers accelerate Pillow
Model:   auto-downloaded from HuggingFace on first use (~1.5GB)
"""

from __future__ import annotations
import io
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_model = None
_processor = None


def _load_model(device: str = "auto"):
    """Load Florence-2 model (cached across calls)."""
    global _model, _processor
    if _model is not None:
        return

    import torch
    from transformers import AutoProcessor, AutoModelForCausalLM

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    # Florence-2-large-ft has updated tokenizer code that works with
    # transformers 4.46+. Fall back to base if ft isn't available.
    model_ids = [
        "microsoft/Florence-2-large-ft",
        "microsoft/Florence-2-large",
    ]

    for model_id in model_ids:
        try:
            logger.info("Loading %s (%s)…", model_id, device)
            _processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
            _model = AutoModelForCausalLM.from_pretrained(
                model_id,
                trust_remote_code=True,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            ).to(device)
            logger.info("Florence-2 loaded on %s (model: %s)", device, model_id)
            return
        except Exception as exc:
            logger.debug("Failed to load %s: %s", model_id, exc)
            _model = _processor = None
            continue

    raise RuntimeError(
        "Could not load Florence-2. Try: pip install transformers==4.45.2 "
        "or check https://huggingface.co/microsoft/Florence-2-large-ft"
    )


def _parse_coordinates(text: str, img_w: int, img_h: int) -> Optional[Tuple[int, int]]:
    """
    Parse Florence-2 grounding output into pixel coordinates.

    Florence returns bounding boxes as normalized <loc_XXX> tokens,
    where XXX is 0-999 representing 0-100% of the image dimension.
    """
    # Pattern: <loc_X1><loc_Y1><loc_X2><loc_Y2>
    locs = re.findall(r"<loc_(\d+)>", text)
    if len(locs) >= 4:
        x1 = int(locs[0]) / 1000 * img_w
        y1 = int(locs[1]) / 1000 * img_h
        x2 = int(locs[2]) / 1000 * img_w
        y2 = int(locs[3]) / 1000 * img_h
        # Return center of bounding box
        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)
        return (cx, cy)
    return None


def locate(image_bytes: bytes, device: str = "auto") -> Optional[Tuple[int, int]]:
    """
    Find the Cloudflare checkbox in a screenshot using Florence-2.

    Parameters
    ----------
    image_bytes : bytes
        PNG screenshot.
    device : str
        "cuda", "cpu", or "auto".

    Returns
    -------
    (x, y) pixel coordinates of the checkbox center, or None.
    """
    from PIL import Image

    _load_model(device)

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_w, img_h = image.size

    # Florence-2 grounding prompt — ask it to find the checkbox
    prompts = [
        "<CAPTION_TO_PHRASE_GROUNDING> Verify you are human checkbox",
        "<CAPTION_TO_PHRASE_GROUNDING> Cloudflare verification checkbox",
        "<CAPTION_TO_PHRASE_GROUNDING> checkbox",
    ]

    for prompt in prompts:
        try:
            inputs = _processor(text=prompt, images=image, return_tensors="pt")
            # Move to same device as model
            dev = next(_model.parameters()).device
            inputs = {k: v.to(dev) if hasattr(v, "to") else v for k, v in inputs.items()}

            import torch
            with torch.no_grad():
                output_ids = _model.generate(
                    **inputs,
                    max_new_tokens=128,
                    num_beams=3,
                )

            text = _processor.batch_decode(output_ids, skip_special_tokens=False)[0]
            result = _parse_coordinates(text, img_w, img_h)
            if result:
                logger.info("Florence-2 found checkbox at (%d, %d) with prompt: %s",
                            result[0], result[1], prompt)
                return result
        except Exception as exc:
            logger.debug("Florence-2 prompt failed (%s): %s", prompt, exc)
            continue

    logger.info("Florence-2 could not locate checkbox")
    return None


def unload():
    """Free model from memory."""
    global _model, _processor
    if _model is not None:
        del _model, _processor
        _model = _processor = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("Florence-2 unloaded")
