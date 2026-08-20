"""Resolve the LLM model string + litellm kwargs from environment.

One server-side model for every tenant, read from .env. Per-tenant model
selection lands with auth/billing later.
"""
import os

from dotenv import load_dotenv

# override=True: this app's repo-root .env is the authoritative LLM config and
# must win over any ambient DEEPSEEK_API_KEY etc. exported in the user's shell
# (e.g. a codex/other-tool key), otherwise .env edits are silently ignored.
load_dotenv(override=True)

# provider -> (model prefix, key env var, default api_base, base override env var)
#  key env:   <PROVIDER>_API_KEY 必填（vllm/ollama 可填 EMPTY 等任意值）
#  base:      os.environ[base_var] 或 default_base 优先；都没有则不传 api_base（litellm 用官方端点）
#             —— base_var 用于走代理 / 内网 / 自建 OpenAI 兼容网关时覆盖默认端点
_PROVIDERS: dict[str, tuple[str, str, str | None, str | None]] = {
    "google": ("", "GOOGLE_API_KEY", None, "GOOGLE_API_BASE"),
    "claude": ("anthropic/", "CLAUDE_API_KEY", None, "CLAUDE_API_BASE"),
    "openai": ("openai/", "OPENAI_API_KEY", "https://api.openai.com/v1", "OPENAI_API_BASE"),
    "deepseek": ("deepseek/", "DEEPSEEK_API_KEY", None, "DEEPSEEK_API_BASE"),
    "ali": ("openai/", "ALI_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1", "ALI_API_BASE"),
    "silicon": ("openai/", "SILICON_API_KEY", "https://api.siliconflow.cn/v1", "SILICON_API_BASE"),
    "modelscope": ("openai/", "MODELSCOPE_API_KEY", "https://api-inference.modelscope.cn/v1", "MODELSCOPE_API_BASE"),
    "doubao": ("openai/", "DOUBAO_API_KEY", "https://ark.cn-beijing.volces.com/api/v3", "DOUBAO_API_BASE"),
    "zhipu": ("openai/", "ZHIPUAI_API_KEY", "https://open.bigmodel.cn/api/paas/v4", "ZHIPUAI_API_BASE"),
    "moonshot": ("moonshot/", "MOONSHOT_API_KEY", "https://api.moonshot.cn/v1", "MOONSHOT_API_BASE"),
    "xai": ("xai/", "XAI_API_KEY", "https://api.x.ai/v1", "XAI_API_BASE"),
    "groq": ("groq/", "GROQ_API_KEY", "https://api.groq.com/openai/v1", "GROQ_API_BASE"),
    "openrouter": ("openrouter/", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "OPENROUTER_API_BASE"),
    "vllm": ("openai/", "VLLM_API_KEY", None, "VLLM_API_BASE"),
    "ollama": ("openai/", "OLLAMA_API_KEY", None, "OLLAMA_API_BASE"),
}


def _kwargs(key_var: str, default_base: str | None, base_var: str | None) -> dict:
    """Build litellm kwargs: api_key if set, api_base = env override or default."""
    kwargs: dict = {}
    key = os.environ.get(key_var)
    if key:
        kwargs["api_key"] = key
    base = os.environ.get(base_var) if base_var else None
    base = base or default_base
    if base:
        kwargs["api_base"] = base
    return kwargs


def resolve_model() -> tuple[str, dict]:
    """Return (litellm_model, kwargs) for the main text model."""
    provider = os.environ.get("MODEL_PROVIDER", "deepseek").lower()
    name = os.environ.get("MODEL_NAME", "deepseek-chat")
    if provider not in _PROVIDERS:
        raise ValueError(f"Unsupported MODEL_PROVIDER: {provider}")
    prefix, key_var, default_base, base_var = _PROVIDERS[provider]
    model = name if name.startswith(prefix) else prefix + name
    return model, _kwargs(key_var, default_base, base_var)


def resolve_vision_model() -> tuple[str, dict] | None:
    """Return (litellm_model, kwargs) for the dedicated vision model.

    None if VISION_MODEL unset -> image-bearing turns fall back to the main model.
    VISION_MODEL is a full litellm model string and may already carry a provider
    prefix (e.g. "openai/qwen-vl-max").
    """
    model = os.environ.get("VISION_MODEL")
    if not model:
        return None
    kwargs = _kwargs("VISION_API_KEY", None, "VISION_API_BASE")
    return model, kwargs


if __name__ == "__main__":
    m, kw = resolve_model()
    assert m, "model string empty"
    print("resolved model:", m, "| kwargs keys:", sorted(kw))
    v = resolve_vision_model()
    print("vision model:", v[0] if v else "(未配置)")
