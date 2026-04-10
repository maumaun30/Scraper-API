import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.config import get_settings
from app.core.database import init_db
from app.services.scheduler import start_scheduler
from app.routers import auth, items, scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

settings = get_settings()
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    start_scheduler()
    yield
    # Shutdown — scheduler stops automatically


app = FastAPI(
    title="Reverse Web Scraper API",
    description=(
        "Scrapes Next.js sites, stores structured content in PostgreSQL, "
        "and pushes to WordPress on a schedule."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(items.router)
app.include_router(scraper.router)


@app.get("/", tags=["health"])
async def health():
    return {"status": "ok", "service": "reverse-scraper-api"}


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "healthy"}
