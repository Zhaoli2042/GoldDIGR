"""
pipeline.agent.vision – Vision model abstraction for locating UI elements.

All providers implement the same interface:
    locate_checkbox(image_bytes: bytes) -> Optional[Tuple[int, int]]

Returns (x, y) viewport coordinates of the Cloudflare checkbox center,
or None if not found.
"""

from __future__ import annotations
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Lazy-loaded model instances (persist across calls within a pipeline run)
_model_cache: dict = {}


def locate_checkbox(
    image_bytes: bytes,
    provider: str = "qwen-vl-local",
    device: str = "auto",
    model_size: str = "3b",
) -> Optional[Tuple[int, int]]:
    """
    Find the Cloudflare verification checkbox in a screenshot.

    Parameters
    ----------
    image_bytes : bytes
        PNG screenshot from driver.get_screenshot_as_png().
    provider : str
        One of: qwen-vl-local, florence-local, claude-api, openai-api
    device : str
        "cuda", "cpu", or "auto" (auto-detect GPU).
    model_size : str
        For qwen-vl-local: "3b" or "7b".

    Returns
    -------
    (x, y) tuple of viewport pixel coordinates, or None if not found.
    """
    if provider == "qwen-vl-local":
        from .qwen_vl import locate
        return locate(image_bytes, device=device, model_size=model_size)
    elif provider == "florence-local":
        from .florence import locate
        return locate(image_bytes, device=device)
    elif provider == "claude-api":
        from .api_provider import locate_claude
        return locate_claude(image_bytes)
    elif provider == "openai-api":
        from .api_provider import locate_openai
        return locate_openai(image_bytes)
    else:
        logger.error("Unknown vision provider: %s", provider)
        return None
