from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import models
from core.database import Base, engine
from auth.routes import router as auth_router
from block_requests.routes import router as block_requests_router

Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="Login API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth_router, prefix="/api")
app.include_router(block_requests_router, prefix="/api")


# Frontend files are inside the docs folder
STATIC_DIR = Path(__file__).resolve().parent.parent / "docs"


# Serve the frontend files directly from /
app.mount(
    "/",
    StaticFiles(directory=STATIC_DIR, html=True),
    name="frontend"
)


app.add_middleware(
    CORSMiddleware,
     allow_origins=[
       "https://devanshulkamboj.github.io",
       "https://marg-ai-26027-2026.netlify.app",
       "http://localhost:5500",
       "http://127.0.0.1:5500",
   ],
    allow_credentials=False,   # you use a Bearer header, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
)