"""Task Service FastAPI application."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.tasks import router as tasks_router
from app.api.webhooks import router as webhooks_router
from app.core.storage import get_storage_instance
from app.scheduler import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = get_storage_instance()
    logger.info(f"Storage backend: {storage.__class__.__name__}")
    await storage.connect()
    scheduler.start()
    yield
    scheduler.stop()
    await storage.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Task Scheduler Service", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(tasks_router)
    app.include_router(webhooks_router)
    logger.info("Task service API ready")
    return app


app = create_app()
