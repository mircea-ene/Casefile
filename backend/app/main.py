import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import tracing
from app.config import get_settings
from app.conversations import fill_interrupted_titles
from app.routers import chat, conversations, documents

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    fill_interrupted_titles()
    yield
    tracing.shutdown()


app = FastAPI(title="Accelerise RAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(conversations.router)


@app.get("/health")
def health():
    return {"status": "ok"}
