"""HTTP server: receive CyCraft webhooks and forward to Stellar XDR."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from app.integrations.cycraft.config import Settings, load_settings
from app.integrations.cycraft.pipeline import ForwardPipeline

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    pipeline = ForwardPipeline(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await pipeline.aclose()
        pipeline.close()

    app = FastAPI(
        title="CyCraft → Stellar XDR Connector",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook/cycraft")
    async def cycraft_webhook(
        request: Request,
        authorization: str | None = Header(default=None),
        x_cycraft_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_webhook_auth(settings, authorization=authorization, token=x_cycraft_token)
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON body must be an object")
        try:
            return await pipeline.forward_raw(payload)
        except Exception as exc:
            logger.exception("Forward failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/webhook/cycraft/batch")
    async def cycraft_webhook_batch(
        request: Request,
        authorization: str | None = Header(default=None),
        x_cycraft_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_webhook_auth(settings, authorization=authorization, token=x_cycraft_token)
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
        items: list[dict[str, Any]]
        if isinstance(payload, list):
            items = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            nested = payload.get("alerts") or payload.get("data") or payload.get("events")
            if isinstance(nested, list):
                items = [item for item in nested if isinstance(item, dict)]
            else:
                items = [payload]
        else:
            raise HTTPException(status_code=400, detail="Unsupported JSON shape")
        results = []
        for item in items:
            try:
                results.append(await pipeline.forward_raw(item))
            except Exception as exc:
                results.append({"error": str(exc), "event": item.get("id")})
        return {"count": len(results), "results": results}

    return app


def _check_webhook_auth(
    settings: Settings,
    *,
    authorization: str | None,
    token: str | None,
) -> None:
    secret = settings.cycraft_webhook_secret.strip()
    if not secret:
        return
    bearer = (authorization or "").removeprefix("Bearer ").strip()
    if bearer == secret or (token or "").strip() == secret:
        return
    raise HTTPException(status_code=401, detail="Invalid webhook credentials")
