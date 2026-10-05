from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress
from app.routes import lead_bot
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from shared.database.service import init_db as connect_service_db, shutdown_db, get_db
from app.routes import (
    categorisation,
    client_intelligence,
    contact_finder,
    free_search,
    linkedin_leads,
    client_leads,
    trainer_profile_leads,
    ai,
    assistant,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_service_db(settings)
    db = await get_db()
    await db['client_leads'].create_index('post_key', unique=True,
        partialFilterExpression={'post_key': {'$type': 'string'}})
    bot_task = asyncio.create_task(lead_bot.run_loop())
    try:
        yield
    finally:
        bot_task.cancel()
        with suppress(asyncio.CancelledError):
            await bot_task
        await shutdown_db()


app = FastAPI(
    title="Intelligence Service",
    description="AI categorisation, client intelligence, contact finder, leads, assistant chat",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categorisation.router,       prefix="/api/v1/intelligence",              tags=["categorisation"])
app.include_router(client_intelligence.router,  prefix="/api/v1/intelligence",              tags=["client-intelligence"])
app.include_router(contact_finder.router,       prefix="/api/v1/contact-finder",            tags=["contact-finder"])
app.include_router(free_search.router,          prefix="/api/v1/intelligence/trainers",     tags=["free-search"])
app.include_router(linkedin_leads.router,        prefix="/api/v1/linkedin-leads",            tags=["linkedin-leads"])
app.include_router(lead_bot.router, prefix='/api/v1/linkedin-leads/bot', tags=['lead-bot'])
app.include_router(client_leads.router,         prefix="/api/v1/client-leads",              tags=["client-leads"])
app.include_router(trainer_profile_leads.router,prefix="/api/v1/trainer-profile-leads",     tags=["trainer-profile-leads"])
app.include_router(ai.router,                   prefix="/api/v1/ai",                        tags=["ai"])
app.include_router(assistant.router,            prefix="/api/v1/assistant",                 tags=["assistant"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}
