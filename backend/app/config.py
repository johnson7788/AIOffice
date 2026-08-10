"""Resolve the LLM model string + litellm kwargs from environment.

M0: one server-side model for every tenant, read from .env. Per-tenant model
selection lands with auth/billing in M1.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# provider -> (model prefix, env var for key, optional fixed api_base, env var for base)
_PROVIDERS: dict[str, tuple[str, str, str | None, str | None]] = {
    "google": ("", "GOOGLE_API_KEY", None, None),
    "claude": ("anthropic/", "CLAUDE_API_KEY", None, None),
    "openai": ("openai/", "OPENAI_API_KEY", "https://api.openai.com/v1", None),
    "deepseek": ("deepseek/", "DEEPSEEK_API_KEY", None, None),
    "ali": ("openai/", "ALI_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1", None),
    "silicon": ("openai/", "SILICON_API_KEY", "https://api.siliconflow.cn/v1", None),
    "modelscope": ("openai/", "MODELSCOPE_API_KEY", "https://api-inference.modelscope.cn/v1", None),
    "doubao": ("openai/", "DOUBAO_API_KEY", "https://ark.cn-beijing.volces.com/api/v3", None),
    "vllm": ("openai/", "VLLM_API_KEY", None, "VLLM_API_URL"),
    "ollama": ("openai/", "OLLAMA_API_KEY", None, "OLLAMA_API_URL"),
}


def resolve_model() -> tuple[str, dict]:
    """Return (litellm_model, kwargs) for litellm.acompletion."""
    provider = os.environ.get("MODEL_PROVIDER", "deepseek").lower()
    name = os.environ.get("MODEL_NAME", "deepseek-chat")
    if provider not in _PROVIDERS:
        raise ValueError(f"Unsupported MODEL_PROVIDER: {provider}")
    prefix, key_var, fixed_base, base_var = _PROVIDERS[provider]
    model = name if name.startswith(prefix) else prefix + name
    kwargs: dict = {}
    key = os.environ.get(key_var)
    if key:
        kwargs["api_key"] = key
    base = fixed_base or (os.environ.get(base_var) if base_var else None)
    if base:
        kwargs["api_base"] = base
    return model, kwargs


if __name__ == "__main__":
    m, kw = resolve_model()
    assert m, "model string empty"
    print("resolved model:", m, "| kwargs keys:", sorted(kw))
