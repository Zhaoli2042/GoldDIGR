"""
cc_detector.py – Detect computational-chemistry content and extract details via LLM.

Combines detect_cc_metadata.py and llm_extract_comp_details_good.py into
a single module with a clean interface.
"""

from __future__ import annotations
import json
import logging
import os
import re
import textwrap
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Default keyword patterns ─────────────────────────────────────────────
DEFAULT_CC_KEYWORDS = [
    "computational", "theoretical", "DFT", "Gaussian", "ORCA", "Jaguar",
    "basis set", "functional", "CCSD", "coupled cluster", "B3LYP", "M06",
    "PBE", "6-31G", "CPCM", "dispersion", "transition state", "frequency",
    "imaginary", "coordinates", "optimization", "solvation", "polarization",
]


def has_cc_content(text: str, keywords: Optional[list[str]] = None) -> bool:
    """Return True if *text* contains computational-chemistry keywords."""
    kw = keywords or DEFAULT_CC_KEYWORDS
    pattern = re.compile("|".join(re.escape(k) for k in kw), re.IGNORECASE)
    return bool(pattern.search(text))


def flag_cc_pages(page_texts: list[str], keywords: Optional[list[str]] = None) -> list[int]:
    """Return indices of pages that contain CC content."""
    return [i for i, text in enumerate(page_texts) if has_cc_content(text, keywords)]


# ── LLM extraction ──────────────────────────────────────────────────────
SYSTEM_MSG = (
    "You are a meticulous computational chemist. "
    "Given a plain-text methods section, you extract structured details."
)

USER_TEMPLATE = textwrap.dedent("""
    **Methods text**
    ----------------
    {text}

    **Task**
    1. Read the text above and identify computational-chemistry details.
    2. Produce a JSON object with these keys (omit any that are not present):
       - "software":            e.g. "Gaussian 16", "ORCA 5.0.4"
       - "level_of_theory":     full string, e.g. "B3LYP-D3(BJ)/6-31G(d,p)"
       - "basis_set":           e.g. "6-31G(d,p)", "def2-TZVP"
       - "functional":          e.g. "B3LYP-D3(BJ)", "PBE0"
       - "method_family":       one or more of ["DFT", "HF", "MP2", "CCSD",
                                "CCSD(T)", "TD-DFT", "semi-empirical", ...]
       - "calculation_types":   from ["geometry_optimization",
                                "transition_state_optimization", "single_point",
                                "frequency_analysis", "vibrational_analysis",
                                "IRC", "NMR", "UV-Vis", "thermochemistry",
                                "MD", "other"]
       - "special_treatments":  solvent model, dispersion, relativistic, etc.
       - "comments":            free-text notes worth keeping
    3. Output **only** a fenced ```json block, nothing else.
""").strip()


def extract_cc_details(
    text: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_chars: int = 200_000,
) -> dict:
    """
    Send text to an LLM and parse the structured comp-chem JSON response.

    Provider/model default to environment variables LLM_PROVIDER / LLM_MODEL.
    """
    provider = provider or os.environ.get("LLM_PROVIDER", "openai")
    model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")

    prompt = USER_TEMPLATE.format(text=text[:max_chars])
    raw = _call_llm(provider, model, prompt)

    # Parse fenced JSON
    try:
        json_block = raw.split("```json")[1].split("```")[0]
    except IndexError:
        # Try to find raw JSON
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            json_block = raw[start:end]
        except ValueError:
            raise ValueError("LLM response contained no JSON block")

    return json.loads(json_block)


def _call_llm(provider: str, model: str, prompt: str) -> str:
    """Dispatch to the appropriate LLM provider."""
    if provider == "openai":
        return _ask_openai(model, prompt)
    elif provider == "anthropic":
        return _ask_anthropic(model, prompt)
    elif provider == "deepseek":
        return _ask_deepseek(model, prompt)
    elif provider == "local":
        return _ask_local(model, prompt)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def _ask_openai(model: str, prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=model, temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_MSG},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content.strip()


def _ask_anthropic(model: str, prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=model, max_tokens=4096, temperature=0.2,
        system=SYSTEM_MSG,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def _ask_deepseek(model: str, prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1",
    )
    resp = client.chat.completions.create(
        model=model, temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_MSG},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content.strip()


def _ask_local(model: str, prompt: str) -> str:
    import requests
    url = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/api/generate")
    r = requests.post(url, json={"model": model, "prompt": prompt, "stream": False}, timeout=120)
    r.raise_for_status()
    return r.json()["response"].strip()
