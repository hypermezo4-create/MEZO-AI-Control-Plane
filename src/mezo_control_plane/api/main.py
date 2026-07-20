from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from mezo_control_plane.api.middleware import (
    AuditLogMiddleware,
    AuthenticationMiddleware,
    BodyLimitMiddleware,
    MetricsMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    TimeoutMiddleware,
    error_response,
)
from mezo_control_plane.api.routes.control import router as control_router
from mezo_control_plane.api.routes.dashboard import router as dashboard_router
from mezo_control_plane.api.routes.health import router as health_router
from mezo_control_plane.api.routes.observability import router as observability_router
from mezo_control_plane.api.routes.tasks import router as tasks_router
from mezo_control_plane.application.errors import ApplicationError, ConflictError, NotFoundError
from mezo_control_plane.application.tasks import TaskApplicationService
from mezo_control_plane.core.settings import Settings, get_settings
from mezo_control_plane.database.repositories import TaskRepository
from mezo_control_plane.database.session import create_engine, create_session_factory
from mezo_control_plane.observability.logging import configure_logging
from mezo_control_plane.observability.metrics import MetricsRegistry
from mezo_control_plane.queue.cancellation import CancellationService
from mezo_control_plane.queue.metrics import QueueMetricsCollector
from mezo_control_plane.queue.producer import TaskProducer


def create_app(
    application: TaskApplicationService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    configuration = settings or get_settings()
    configure_logging(configuration.log_level)
    application_metrics = MetricsRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if application is not None:
            app.state.application = application
            yield
            return
        engine = create_engine(configuration.database_url)
        sessions = create_session_factory(engine)
        redis = Redis.from_url(configuration.redis_url, decode_responses=True)

        async def database_health() -> bool:
            try:
                async with sessions() as session:
                    await session.execute(text("SELECT 1"))
                return True
            except Exception:
                return False

        async def redis_health() -> bool:
            try:
                return bool(await redis.ping())
            except Exception:
                return False

        metrics = QueueMetricsCollector(redis)

        async def worker_health() -> bool:
            try:
                return (await metrics.snapshot()).active_workers > 0
            except Exception:
                return False

        async def configuration_health() -> bool:
            api_key = configuration.control_plane_api_key.get_secret_value()
            return bool(
                api_key
                and api_key != "replace-me"
                and configuration.database_url
                and configuration.redis_url
            )

        app.state.application = TaskApplicationService(
            TaskRepository(sessions),
            TaskProducer(redis),
            CancellationService(redis),
            database_health,
            redis_health,
            worker_health,
            configuration_health,
        )
        app.state.queue_metrics = metrics
        app.state.redis = redis
        app.state.engine = engine
        yield
        await redis.aclose()
        await engine.dispose()

    app = FastAPI(
        title="MEZO AI Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = configuration
    app.state.application_metrics = application_metrics
    if application is not None:
        app.state.application = application
    app.include_router(health_router)
    app.include_router(tasks_router)
    app.include_router(control_router)
    app.include_router(observability_router)
    app.include_router(dashboard_router)
    app.add_middleware(AuditLogMiddleware)
    app.add_middleware(MetricsMiddleware, registry=application_metrics)
    app.add_middleware(
        RateLimitMiddleware,
        limit=configuration.api_rate_limit_requests,
        window_seconds=configuration.api_rate_limit_window_seconds,
    )
    app.add_middleware(TimeoutMiddleware, timeout_seconds=configuration.api_timeout_seconds)
    app.add_middleware(BodyLimitMiddleware, maximum_bytes=configuration.api_body_limit_bytes)
    app.add_middleware(
        AuthenticationMiddleware,
        api_key=configuration.control_plane_api_key.get_secret_value(),
    )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, error: ApplicationError) -> JSONResponse:
        code = (
            404
            if isinstance(error, NotFoundError)
            else 409
            if isinstance(error, ConflictError)
            else 400
        )
        return error_response(request, error.code, str(error), code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(request, "validation_error", "Request validation failed", 422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(request, "http_error", str(error.detail), error.status_code)

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run("mezo_control_plane.api.main:app", host=settings.host, port=settings.port)
