"""FastAPI application entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import datasets, ml, misc, query
from app.core.config import get_settings
from app.database.db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

settings = get_settings()
init_db()

app = FastAPI(title="Data Analyst + ML Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    # Comma-separated list; trailing slashes ignored so "https://x.vercel.app/" still matches.
    allow_origins=[o.strip().rstrip("/") for o in settings.FRONTEND_URL.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # HTTPException details are raised deliberately by our own code and are safe to return.
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces or file system paths to the client — log server-side only.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "An internal error occurred. Please try again."})


app.include_router(misc.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(ml.router, prefix="/api")


@app.get("/")
def root():
    return {"name": "Data Analyst + ML Agent API", "docs": "/docs"}
