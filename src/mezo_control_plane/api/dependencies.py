import secrets

from fastapi import Header, HTTPException, status

from mezo_control_plane.core.settings import get_settings


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    expected = get_settings().control_plane_api_key.get_secret_value()
    if not expected or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
