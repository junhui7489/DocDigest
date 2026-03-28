"""FastAPI application entry point.

In development:
  - Frontend runs on Vite dev server (port 3000)
  - Vite proxies /api → FastAPI (port 8000)

In production:
  - FastAPI serves the built frontend from frontend/dist/
  - Both API and UI served from the same origin
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.config import settings
from app.models.database import engine, Base
from app.routers import documents

# Path to the built frontend (created by `npm run build` in frontend/)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: ensure upload directory exists
    settings.ensure_upload_dir()

    # Startup: enable pgvector and create database tables
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    yield

    # Shutdown: dispose database engine
    await engine.dispose()


app = FastAPI(
    title="DocDigest API",
    description="LLM-powered document analysis and summarisation.",
    version="0.1.0",
    lifespan=lifespan,
)

# --- CORS ---
# Origins are comma-separated in ALLOWED_ORIGINS env var.
# Defaults to localhost for dev; set to Vercel URL in production.
_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Routers ---
app.include_router(
    documents.router,
    prefix="/api/v1/documents",
    tags=["documents"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "0.1.0"}


# --- Serve built frontend (production) ---
# Mount static assets (JS/CSS/images) if the build exists.
# The catch-all route below serves index.html for client-side routing.
if FRONTEND_DIR.exists():
    # Serve /assets/* directly
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="frontend-assets",
        )

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve the frontend SPA.

        - If the requested file exists in the build directory, serve it.
        - Otherwise, serve index.html (for client-side routing).
        """
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        # Fall back to index.html for SPA routing
        return FileResponse(str(FRONTEND_DIR / "index.html"))
