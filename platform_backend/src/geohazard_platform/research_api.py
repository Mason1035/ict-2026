"""Separate GET-only router. Authorization is supplied by the composition root."""
from fastapi import APIRouter, HTTPException, Query
import sqlite3

from .research_display import ResearchDisplay, ResearchDisplayError


def research_router(display: ResearchDisplay, authorize):
    from fastapi import Depends
    router = APIRouter(prefix="/api/research", dependencies=[Depends(authorize)], tags=["research"])

    def read(operation, *args):
        try:
            return operation(*args)
        except ResearchDisplayError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
            # Keep local paths/private raw contents out of HTTP error bodies.
            raise HTTPException(409, "研究原件、登记或冻结配置校验失败；请离线复核") from exc

    @router.get("/sessions")
    def sessions():
        return read(display.sessions)

    @router.get("/sessions/{experiment_id}")
    def detail(experiment_id: str, max_points: int = Query(600, ge=16, le=2000)):
        return read(display.detail, experiment_id, max_points)

    @router.get("/sessions/{experiment_id}/rules")
    def rules(experiment_id: str):
        return read(display.rules, experiment_id)

    return router
