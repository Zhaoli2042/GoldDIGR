"""Shared utility functions for pipeline.plugins modules."""
from __future__ import annotations

import re
from typing import Dict


# ═══════════════════════════════════════════════════════════════════════
# LLM client
# ═══════════════════════════════════════════════════════════════════════

def call_llm(
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    *,
    timeout: int = 300,
    max_tokens: int = 8192,
) -> str:
    """Call an LLM provider and return the response text.

    Parameters
    ----------
    provider : str
        "openai" or "anthropic"
    model : str
        Model identifier (e.g. "gpt-4o", "claude-sonnet-4-20250514")
    system_prompt : str
        System-level instruction
    user_prompt : str
        User message content
    temperature : float
        Sampling temperature (default 0.2)
    timeout : int
        HTTP request timeout in seconds (default 300)
    max_tokens : int
        Max tokens for Anthropic responses (default 8192)
    """
    import os
    import requests

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set.")
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": model, "temperature": temperature,
                  "messages": [{"role": "system", "content": system_prompt},
                               {"role": "user", "content": user_prompt}]},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set.")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "temperature": temperature,
                  "system": system_prompt,
                  "messages": [{"role": "user", "content": user_prompt}]},
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json().get("content", [])
        return "".join(c["text"] for c in content if c.get("type") == "text")

    raise ValueError(f"Unknown provider: {provider}")


# ═══════════════════════════════════════════════════════════════════════
# Interactive CLI helpers
# ═══════════════════════════════════════════════════════════════════════

def ask_user(question: str, default: str = "") -> str:
    """Prompt the user for input with an optional default."""
    prompt = f"  {question} [{default}]: " if default else f"  {question}: "
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer if answer else default


def confirm(message: str) -> bool:
    """Ask the user a yes/no question, defaulting to yes."""
    try:
        answer = input(f"  {message} [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "y", "yes")


# ═══════════════════════════════════════════════════════════════════════
# LLM output parsing
# ═══════════════════════════════════════════════════════════════════════

def parse_multi_file_output(raw: str) -> Dict[str, str]:
    """Parse LLM output with ``=== FILE: ... ===`` markers into a dict."""
    files: Dict[str, str] = {}
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    parts = re.split(r"^=== FILE:\s*(.+?)\s*===\s*$", raw, flags=re.MULTILINE)
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            fname = parts[i].strip()
            content = parts[i + 1].strip() + "\n" if i + 1 < len(parts) else ""
            files[fname] = content
    elif raw.strip():
        files["glue/prepare_and_launch.sh"] = raw

    return files


def fix_yaml_quoting(yaml_text: str) -> str:
    """Fix common YAML issues — mainly unquoted values containing colons.

    E.g.: ``description: count electrons: if even -> 1``
    becomes: ``description: "count electrons: if even -> 1"``
    """
    fixed_lines = []
    for line in yaml_text.splitlines():
        stripped = line.lstrip()

        # Skip comments, blank lines, block scalars, already-quoted lines
        if (not stripped or stripped.startswith("#") or
                stripped.startswith("-") and ":" not in stripped):
            fixed_lines.append(line)
            continue

        # Match: "  key: value" where value contains another colon
        # But skip lines that are already quoted, use >, |, or are list items
        m = re.match(r'^(\s*)([\w_.-]+):\s+(.+)$', line)
        if m:
            indent = m.group(1)
            key = m.group(2)
            value = m.group(3).strip()

            # Check if value has problematic characters and isn't already quoted
            needs_quoting = (
                ':' in value and
                not value.startswith('"') and
                not value.startswith("'") and
                not value.startswith('>') and
                not value.startswith('|') and
                not value.startswith('[') and
                not value.startswith('{')
            )

            if needs_quoting:
                # Escape existing double quotes in the value
                value_escaped = value.replace('"', '\\"')
                fixed_lines.append(f'{indent}{key}: "{value_escaped}"')
                continue

        fixed_lines.append(line)

    return "\n".join(fixed_lines)
