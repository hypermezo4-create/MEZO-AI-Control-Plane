from enum import StrEnum

from pydantic import BaseModel, Field


class TelegramRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class TelegramMessage(BaseModel):
    message_id: int
    chat_id: int
    user_id: int
    text: str = Field(max_length=20_000)


class TelegramCallback(BaseModel):
    callback_id: str
    chat_id: int
    user_id: int
    data: str = Field(max_length=512)


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None
    callback: TelegramCallback | None = None


class CommandRequest(BaseModel):
    name: str
    arguments: str
    update_id: int
    chat_id: int
    user_id: int
    role: TelegramRole
