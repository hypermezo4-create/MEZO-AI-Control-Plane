from typing import Annotated, cast

from fastapi import Depends, Request

from mezo_control_plane.application.tasks import TaskApplicationService
from mezo_control_plane.core.settings import Settings


def application_service(request: Request) -> TaskApplicationService:
    return cast(TaskApplicationService, request.app.state.application)


ServiceDependency = Annotated[TaskApplicationService, Depends(application_service)]


def application_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


SettingsDependency = Annotated[Settings, Depends(application_settings)]
