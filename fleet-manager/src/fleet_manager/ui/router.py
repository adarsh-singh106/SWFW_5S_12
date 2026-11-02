"""Router serving the browser-based Fleet Operations Dashboard."""

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])

_INDEX_HTML_PATH = Path(__file__).resolve().parent / "index.html"


@lru_cache(maxsize=1)
def _load_dashboard_html() -> str:
    return _INDEX_HTML_PATH.read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def get_dashboard() -> HTMLResponse:
    """Serve the single-page operations dashboard."""
    html_content = _load_dashboard_html()
    return HTMLResponse(
        content=html_content,
        headers={
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )
