"""
API providers – Claude and OpenAI vision APIs for checkbox detection.

Tier 3 fallback when local models aren't available or fail.
Cost: ~$0.01-0.05 per screenshot.

Requires API key in environment:
  - ANTHROPIC_API_KEY for Claude
  - OPENAI_API_KEY for OpenAI
"""

from __future__ import annotations
import base64
import io
import json
import logging
import os
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_PROMPT = (
    "This is a screenshot of a computer screen showing a Cloudflare verification page "
    "in a web browser. There is a widget with a square checkbox on the LEFT side and "
    "a Cloudflare logo on the RIGHT side. "
    "I need to click the SQUARE CHECKBOX on the LEFT, NOT the Cloudflare logo. "
    "Return the pixel coordinates of the EXACT CENTER of the square checkbox. "
    "Return ONLY JSON: "
    '{\"x\": <number>, \"y\": <number>}. '
    "No other text."
)


def _parse_coordinates(text: str) -> Optional[Tuple[int, int]]:
    """Extract (x, y) from model response."""
    # JSON: {"x": 123, "y": 456}
    try:
        json_match = re.search(r'\{[^}]*\}', text)
        if json_match:
            data = json.loads(json_match.group())
            if "x" in data and "y" in data:
                return (int(data["x"]), int(data["y"]))
    except (json.JSONDecodeError, ValueError):
        pass

    # Parentheses: (123, 456)
    paren = re.search(r'\((\d+)\s*,\s*(\d+)\)', text)
    if paren:
        return (int(paren.group(1)), int(paren.group(2)))

    return None


def _get_image_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    """Get image width and height without PIL."""
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes))
    return img.size


def locate_claude(image_bytes: bytes) -> Optional[Tuple[int, int]]:
    """
    Find checkbox using Anthropic Claude API.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping Claude vision")
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed (pip install anthropic)")
        return None

    b64 = base64.b64encode(image_bytes).decode()
    w, h = _get_image_dimensions(image_bytes)
    prompt = _PROMPT + f" Image dimensions: {w}x{h} pixels."

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=128,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )

        text = response.content[0].text
        logger.debug("Claude response: %s", text)

        result = _parse_coordinates(text)
        if result:
            logger.info("Claude found checkbox at (%d, %d)", result[0], result[1])
        return result

    except Exception as exc:
        logger.warning("Claude API call failed: %s", exc)
        return None


def locate_openai(image_bytes: bytes) -> Optional[Tuple[int, int]]:
    """
    Find checkbox using OpenAI GPT-4o API.
    Requires OPENAI_API_KEY environment variable.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set, skipping OpenAI vision")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed (pip install openai)")
        return None

    b64 = base64.b64encode(image_bytes).decode()
    w, h = _get_image_dimensions(image_bytes)
    prompt = _PROMPT + f" Image dimensions: {w}x{h} pixels."

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=128,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                            "detail": "high",
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )

        text = response.choices[0].message.content
        logger.debug("OpenAI response: %s", text)

        result = _parse_coordinates(text)
        if result:
            logger.info("OpenAI found checkbox at (%d, %d)", result[0], result[1])
        return result

    except Exception as exc:
        logger.warning("OpenAI API call failed: %s", exc)
        return None
