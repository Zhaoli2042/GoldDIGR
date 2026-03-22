"""
pipeline.agent.solver – Orchestrate automated Cloudflare challenge solving.

Flow:
  1. Take FULL SCREEN screenshot (not viewport)
  2. Send to vision model → returns screen coordinates directly
  3. xdotool clicks at those exact coordinates
  4. No coordinate conversion needed — same coordinate space

Each provider is tried in order until one succeeds. If all fail,
returns False so the caller can fall back to interactive mode.
"""

from __future__ import annotations
import io
import logging
import time
from pathlib import Path
from typing import Optional

from .clicker import click_at
from .vision import locate_checkbox

logger = logging.getLogger(__name__)


def _take_screen_screenshot() -> Optional[bytes]:
    """
    Take a full-screen screenshot and return as PNG bytes.
    Tries mss first (fast, reliable), falls back to Pillow.ImageGrab.
    """
    # Try mss
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            img = sct.grab(monitor)
            # Convert to PNG bytes
            from PIL import Image
            pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return buf.getvalue()
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("mss screenshot failed: %s", exc)

    # Try Pillow ImageGrab
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:
        logger.debug("ImageGrab screenshot failed: %s", exc)

    # Try scrot (Linux command-line tool)
    try:
        import subprocess, tempfile
        tmp = tempfile.mktemp(suffix=".png")
        subprocess.run(["scrot", tmp], capture_output=True, timeout=5)
        data = Path(tmp).read_bytes()
        Path(tmp).unlink(missing_ok=True)
        return data
    except Exception:
        pass

    logger.warning("Could not take screen screenshot (install mss: pip install mss)")
    return None


def attempt_click(
    driver,
    config: Optional[dict] = None,
) -> bool:
    """
    Attempt to automatically solve a Cloudflare challenge by finding
    and clicking the verification checkbox.

    Uses full-screen screenshots so model coordinates are screen
    coordinates — no viewport-to-screen conversion needed.

    Parameters
    ----------
    driver : WebDriver
        Selenium Chrome driver with the challenge page loaded.
    config : dict, optional
        Agent config section from config.yaml.

    Returns
    -------
    bool
        True if the challenge was cleared, False otherwise.
    """
    config = config or {}
    providers = config.get("providers", ["qwen-vl-local"])
    max_attempts = config.get("max_attempts", 2)
    device = config.get("device", "auto")
    model_size = config.get("model_size", "3b")

    for provider in providers:
        logger.info("Agent: trying %s to solve Cloudflare challenge", provider)

        for attempt in range(1, max_attempts + 1):
            logger.info("Agent: %s attempt %d/%d", provider, attempt, max_attempts)

            # Step 1: Full screen screenshot
            screenshot = _take_screen_screenshot()
            if not screenshot:
                logger.warning("Agent: screen screenshot failed")
                break

            # Step 2: Locate checkbox
            coords = locate_checkbox(screenshot, provider=provider, device=device, model_size=model_size)
            if coords is None:
                logger.info("Agent: %s could not find checkbox", provider)
                if attempt < max_attempts:
                    time.sleep(2)
                continue

            x, y = coords
            logger.info("Agent: %s found checkbox at screen (%d, %d)", provider, x, y)

            # Save debug screenshot with crosshair
            try:
                from PIL import Image, ImageDraw
                img = Image.open(io.BytesIO(screenshot))
                draw = ImageDraw.Draw(img)
                size = 20
                draw.line([(x - size, y), (x + size, y)], fill="red", width=3)
                draw.line([(x, y - size), (x, y + size)], fill="red", width=3)
                draw.ellipse([(x - 15, y - 15), (x + 15, y + 15)], outline="red", width=2)
                debug_path = Path("data/db/agent_debug.png")
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(debug_path))
                logger.info("Agent: debug screenshot (%dx%d) saved → %s",
                            img.size[0], img.size[1], debug_path)
            except Exception:
                pass

            # Step 3: Click with jitter — try center first, then offsets
            click_offsets = [
                (0, 0),
                (8, 8),
                (-8, -8),
                (12, 0),
                (0, 12),
            ]

            for dx, dy in click_offsets:
                cx, cy = x + dx, y + dy
                clicked = click_at(cx, cy)
                if not clicked:
                    logger.warning("Agent: click failed (no clicking tool available)")
                    return False

                time.sleep(5)

                # Verify
                try:
                    html = driver.page_source
                    from ..scraper import _is_bot_challenge
                    if not _is_bot_challenge(html):
                        logger.info("Agent: challenge cleared by %s at offset (%+d, %+d)!",
                                    provider, dx, dy)
                        return True
                    else:
                        if dx == 0 and dy == 0:
                            logger.info("Agent: center click didn't clear, trying offsets…")
                except Exception as exc:
                    logger.warning("Agent: verification failed: %s", exc)

            # Brief pause before retry
            if attempt < max_attempts:
                time.sleep(2)

        logger.info("Agent: %s exhausted (%d attempts)", provider, max_attempts)

    logger.info("Agent: all providers failed")
    return False


def unload_models() -> None:
    """Free all loaded vision models from memory."""
    try:
        from .vision.florence import unload as unload_florence
        unload_florence()
    except Exception:
        pass
    try:
        from .vision.qwen_vl import unload as unload_qwen
        unload_qwen()
    except Exception:
        pass
