"""
pipeline.agent.clicker – OS-level cursor movement and clicking.

Moves the real mouse cursor via system tools, not JavaScript.
Cloudflare cannot detect this because it's indistinguishable from
a human moving the mouse.

Supports:
  - Linux: xdotool
  - macOS: cliclick
  - Fallback: pyautogui (cross-platform, pip install pyautogui)
"""

from __future__ import annotations
import logging
import platform
import random
import shutil
import subprocess
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _find_tool() -> Optional[str]:
    """Detect which clicking tool is available."""
    system = platform.system()
    if system == "Linux":
        if shutil.which("xdotool"):
            return "xdotool"
    elif system == "Darwin":
        if shutil.which("cliclick"):
            return "cliclick"
    try:
        import pyautogui
        return "pyautogui"
    except ImportError:
        pass
    return None


def _humanize_move(
    tool: str,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    steps: int = 5,
) -> None:
    """
    Move the cursor in small steps with random jitter to look natural.
    """
    for i in range(1, steps + 1):
        frac = i / steps
        x = int(start_x + (end_x - start_x) * frac + random.randint(-3, 3))
        y = int(start_y + (end_y - start_y) * frac + random.randint(-3, 3))

        if tool == "xdotool":
            subprocess.run(
                ["xdotool", "mousemove", "--sync", str(x), str(y)],
                capture_output=True, timeout=5,
            )
        elif tool == "cliclick":
            subprocess.run(
                ["cliclick", f"m:{x},{y}"],
                capture_output=True, timeout=5,
            )
        elif tool == "pyautogui":
            import pyautogui
            pyautogui.moveTo(x, y, duration=0)

        time.sleep(random.uniform(0.03, 0.08))


def click_at(screen_x: int, screen_y: int) -> bool:
    """
    Click at screen coordinates using OS-level cursor movement.

    Parameters
    ----------
    screen_x, screen_y : int
        Absolute screen pixel coordinates (from a full-screen screenshot).

    Returns
    -------
    bool
        True if the click was executed, False if no clicking tool available.
    """
    tool = _find_tool()
    if not tool:
        logger.warning(
            "No clicking tool available. Install xdotool (Linux), "
            "cliclick (macOS), or pyautogui (pip install pyautogui)."
        )
        return False

    logger.info("Clicking at screen (%d, %d) via %s", screen_x, screen_y, tool)

    # Get current mouse position for humanized movement
    try:
        if tool == "xdotool":
            result = subprocess.run(
                ["xdotool", "getmouselocation"],
                capture_output=True, text=True, timeout=5,
            )
            parts = result.stdout.split()
            cur_x = int(parts[0].split(":")[1])
            cur_y = int(parts[1].split(":")[1])
        else:
            cur_x, cur_y = screen_x - 100, screen_y - 50
    except Exception:
        cur_x, cur_y = screen_x - 100, screen_y - 50

    # Move to target with human-like motion
    _humanize_move(tool, cur_x, cur_y, screen_x, screen_y)

    # Small pause before clicking
    time.sleep(random.uniform(0.1, 0.3))

    # Click
    if tool == "xdotool":
        subprocess.run(
            ["xdotool", "mousemove", "--sync", str(screen_x), str(screen_y)],
            capture_output=True, timeout=5,
        )
        time.sleep(0.05)
        subprocess.run(
            ["xdotool", "click", "1"],
            capture_output=True, timeout=5,
        )
    elif tool == "cliclick":
        subprocess.run(
            ["cliclick", f"c:{screen_x},{screen_y}"],
            capture_output=True, timeout=5,
        )
    elif tool == "pyautogui":
        import pyautogui
        pyautogui.click(screen_x, screen_y)

    logger.info("Click executed at screen (%d, %d)", screen_x, screen_y)
    return True
