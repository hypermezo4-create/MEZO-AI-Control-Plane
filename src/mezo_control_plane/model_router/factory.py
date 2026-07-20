from pathlib import Path

from mezo_control_plane.core.settings import Settings
from mezo_control_plane.model_router.configuration import load_router
from mezo_control_plane.model_router.router import ModelRouter
from mezo_control_plane.providers.base import ModelProvider
from mezo_control_plane.providers.gemini import GeminiProvider
from mezo_control_plane.providers.qwen import QwenProvider


def build_model_router(settings: Settings, config_path: Path | None = None) -> ModelRouter:
    gemini_models = frozenset({"gemini-pro", "gemini-flash"})
    providers: dict[str, ModelProvider] = {
        "gemini-a": GeminiProvider(
            "gemini-a",
            settings.gemini_api_key_primary.get_secret_value(),
            settings.gemini_project_primary,
            gemini_models,
            timeout_seconds=settings.model_timeout_seconds,
            retry_budget=settings.model_max_retries,
        ),
        "gemini-b": GeminiProvider(
            "gemini-b",
            settings.gemini_api_key_secondary.get_secret_value(),
            settings.gemini_project_secondary,
            gemini_models,
            timeout_seconds=settings.model_timeout_seconds,
            retry_budget=settings.model_max_retries,
        ),
        "qwen": QwenProvider(
            settings.qwen_base_url,
            settings.qwen_api_key.get_secret_value(),
            frozenset({"qwen-coder"}),
            timeout_seconds=settings.model_timeout_seconds,
        ),
    }
    path = config_path or Path(__file__).with_name("routes.v1.yaml")
    return load_router(path, providers)
