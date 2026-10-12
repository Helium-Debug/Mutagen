"""
MUTAGEN FastAPI application definition.
"""

from __future__ import annotations

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from mutagen import __version__
from mutagen.api.routes.auth import router as auth_router
from mutagen.api.routes.projects import router as projects_router
from mutagen.api.routes.experiments import router as experiments_router
from mutagen.api.routes.mutations import router as mutations_router
from mutagen.db.session import check_database_connection


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="MUTAGEN API",
        description="The Experimental Evolution Engine for Code API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # V1 API Router
    v1_router = APIRouter(prefix="/api/v1")
    v1_router.include_router(auth_router)
    v1_router.include_router(projects_router)
    v1_router.include_router(experiments_router)
    v1_router.include_router(mutations_router)

    @v1_router.get("/health", tags=["health"])
    @app.get("/health", tags=["health"])
    def health_check():
        """Public health check endpoint."""
        db_ok, db_msg = check_database_connection()
        return {
            "status": "healthy" if db_ok else "degraded",
            "version": __version__,
            "database": db_msg,
        }

    app.include_router(v1_router)

    return app


app = create_app()
