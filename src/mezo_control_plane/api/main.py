import uvicorn
from fastapi import FastAPI

from mezo_control_plane.api.routes.health import router as health_router
from mezo_control_plane.api.routes.tasks import router as tasks_router
from mezo_control_plane.core.settings import get_settings
from mezo_control_plane.observability.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="MEZO AI Control Plane", version="0.1.0")
    app.include_router(health_router)
    app.include_router(tasks_router)
    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run("mezo_control_plane.api.main:app", host=settings.host, port=settings.port)
