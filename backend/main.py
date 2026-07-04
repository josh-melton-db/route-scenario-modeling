"""FastAPI entry point.

The app mounts:
  /api  -> JSON endpoints (see backend/routes/api.py)
  /     -> the built React SPA from ./dist (when present)

In local dev only `/api` is served; the React dev server proxies `/api`
back to this process on port 8001.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes.api import router as api_router

api_app = FastAPI(title="Route Scenario Modeling API")
api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
api_app.include_router(api_router)

app = FastAPI(title="Route Scenario Modeling")
app.mount("/api", api_app)


def _resolve_dist_path() -> Path | None:
    root = Path(__file__).parent.parent
    configured = os.getenv("APP_DIST_DIR", "").strip()
    candidates = [configured] if configured else ["dist"]
    for candidate in candidates:
        if not candidate:
            continue
        dist_path = root / candidate
        if dist_path.exists():
            return dist_path
    return None


dist_path = _resolve_dist_path()
if dist_path is not None:
    assets_dir = dist_path / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        if "." in full_path.split("/")[-1]:
            file_path = dist_path / full_path
            if file_path.exists():
                return FileResponse(file_path)
        return FileResponse(dist_path / "index.html")

else:

    @app.get("/")
    async def dev_root() -> dict[str, str]:
        return {
            "message": "Dev mode — run `npm run dev` for the React app.",
            "api_health": "http://localhost:8001/api/health",
            "api_docs": "http://localhost:8001/docs",
        }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
