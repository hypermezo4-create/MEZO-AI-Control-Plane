from mezo_control_plane.core.settings import Settings
from mezo_control_plane.model_router.router import ModelRole, ModelRouter, Route
from mezo_control_plane.providers.gemini import GeminiProvider
from mezo_control_plane.providers.qwen import QwenProvider


def build_model_router(settings: Settings) -> ModelRouter:
    primary = GeminiProvider(
        settings.gemini_api_key_primary.get_secret_value(), settings.model_timeout_seconds
    )
    secondary = GeminiProvider(
        settings.gemini_api_key_secondary.get_secret_value(), settings.model_timeout_seconds
    )
    qwen = QwenProvider(
        settings.qwen_base_url,
        settings.qwen_api_key.get_secret_value(),
        settings.model_timeout_seconds,
    )
    return ModelRouter(
        {
            ModelRole.FAST: [
                Route(primary, settings.gemini_primary_model),
                Route(secondary, settings.gemini_primary_model),
            ],
            ModelRole.PLANNER: [
                Route(primary, settings.gemini_review_model),
                Route(qwen, settings.qwen_model),
                Route(secondary, settings.gemini_review_model),
            ],
            ModelRole.EXECUTOR: [
                Route(qwen, settings.qwen_model),
                Route(primary, settings.gemini_primary_model),
                Route(secondary, settings.gemini_primary_model),
            ],
            ModelRole.REVIEWER: [
                Route(secondary, settings.gemini_review_model),
                Route(qwen, settings.qwen_model),
            ],
            ModelRole.FALLBACK: [
                Route(qwen, settings.qwen_model),
                Route(secondary, settings.gemini_primary_model),
            ],
        },
        max_retries=settings.model_max_retries,
    )
