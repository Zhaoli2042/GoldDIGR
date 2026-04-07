from .qwen_vl import locate as _locate_qwen
from .api_provider import locate_claude, locate_openai

def locate_checkbox(screenshot_bytes, *, provider="qwen-vl-local", device="auto", model_size="3b"):
    """Route to the right vision provider."""
    if provider == "qwen-vl-local":
        return _locate_qwen(screenshot_bytes, device=device, model_size=model_size)
    elif provider == "florence-local":
        from .florence import locate as _locate_florence
        return _locate_florence(screenshot_bytes, device=device)
    elif provider == "claude-api":
        return locate_claude(screenshot_bytes)
    elif provider == "openai-api":
        return locate_openai(screenshot_bytes)
    else:
        raise ValueError(f"Unknown vision provider: {provider}")
