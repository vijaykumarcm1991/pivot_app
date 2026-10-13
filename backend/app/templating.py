"""
One shared Jinja2Templates instance for every page route.

Exposes template globals used by the app shell (`base.html`):
  - app_name()     → the Application Name from the Settings page
                      (cached for a few seconds)
  - app_version    → APP_VERSION
"""
import time

from fastapi.templating import Jinja2Templates

from app.models.app_settings import APP_VERSION

templates = Jinja2Templates(directory="app/templates")

_NAME_CACHE = {"value": None, "at": 0.0}
_NAME_TTL = 15.0


def app_name() -> str:
    now = time.monotonic()
    if _NAME_CACHE["value"] and now - _NAME_CACHE["at"] < _NAME_TTL:
        return _NAME_CACHE["value"]
    name = "Pivot App"
    try:
        from app.config.database import SessionLocal
        from app.repositories.app_settings_repository import get_settings

        db = SessionLocal()
        try:
            row = get_settings(db)
            if row and (row.application_name or "").strip():
                name = row.application_name.strip()
        finally:
            db.close()
    except Exception:
        pass
    _NAME_CACHE["value"] = name
    _NAME_CACHE["at"] = now
    return name


def invalidate_app_name() -> None:
    _NAME_CACHE["value"] = None


templates.env.globals["app_name"] = app_name
templates.env.globals["app_version"] = APP_VERSION
