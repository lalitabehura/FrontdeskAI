"""Serves the embeddable loader script and the sandboxed chat frame.

The frame's CSP `frame-ancestors` is built from the business's allowed domains, so browsers refuse
to embed a business's assistant on sites it hasn't approved."""
import json
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.models import AssistantConfig

router = APIRouter(include_in_schema=False)
_DIR = Path(__file__).resolve().parent.parent / "widget"


@lru_cache
def _file(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


def _js_literal(value: str) -> str:
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def frame_ancestors(domains: list[str]) -> str:
    if not domains:
        return "*"
    out = [get_settings().frontend_url.rstrip("/")]  # the dashboard's live preview
    for d in domains:
        out += [f"https://{d}"] + ([f"http://{d}"] if d.startswith("localhost") else [])
    return " ".join(out)


@router.get("/widget.js")
def loader():
    return Response(_file("loader.js"), media_type="application/javascript; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=300", "Cross-Origin-Resource-Policy": "cross-origin"})


@router.get("/widget/{key}", response_class=HTMLResponse)
def frame(key: str, page: str = Query(default="", max_length=500), db: Session = Depends(get_db)):
    cfg = db.scalar(select(AssistantConfig).where(AssistantConfig.widget_key == key)) if len(key) <= 48 else None
    if cfg is None:
        return HTMLResponse("<!doctype html><title>Not found</title>", status_code=404)
    nonce = secrets.token_urlsafe(16)
    html = (_file("frame.html").replace("{{NONCE}}", nonce).replace("{{KEY}}", _js_literal(key))
            .replace("{{PAGE}}", _js_literal(page)))
    csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
           f"img-src 'self' data:; base-uri 'none'; form-action 'none'; "
           f"frame-ancestors {frame_ancestors(cfg.allowed_domains or [])}")
    return HTMLResponse(html, headers={"Content-Security-Policy": csp, "Cache-Control": "no-store",
                                       "Referrer-Policy": "strict-origin-when-cross-origin"})
