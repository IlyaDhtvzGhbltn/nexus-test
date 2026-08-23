import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.config import get_settings
from app.db import TORTOISE_ORM
from app.routers import auth, npm, repositories, users
from app.seed import seed_initial_data

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP: схема создаётся напрямую (generate_schemas). В продакшене — миграции aerich
    # (aerich init -t app.db.TORTOISE_ORM && aerich init-db / upgrade).
    async with RegisterTortoise(app, config=TORTOISE_ORM, generate_schemas=True):
        await seed_initial_data()
        yield


app = FastAPI(
    title="Artifact Repository",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(repositories.router)
app.include_router(npm.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
