"""
pipeline.agent – Automated Cloudflare CAPTCHA solving.

Default: Qwen2.5-VL-3B (reliable, ~7GB VRAM, ~1s)
Optional: Qwen2.5-VL-7B (more accurate, ~16GB VRAM, ~2s)
Fallback: Claude/OpenAI API (~$0.01/call, no GPU needed)

Usage:
    from pipeline.agent import attempt_click
    if attempt_click(driver, config):
        # challenge cleared
"""

from .solver import attempt_click

__all__ = ["attempt_click"]
