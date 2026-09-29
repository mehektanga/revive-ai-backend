from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database.session import engine, Base, SessionLocal
from app.api.routes import router
from app.simulator.generator import seed_database

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ReviveAI - Autonomous AI Revenue Recovery Agent",
    description="Control tower for payment failure monitoring, root-cause diagnosis, risk-gated recovery, and Razorpay sandbox integration.",
    version="1.0.0"
)

import os

frontend_url = os.getenv("FRONTEND_URL", "*")
origins = [origin.strip() for origin in frontend_url.split(",")] if frontend_url != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        seed_database(db, 10500)
    finally:
        db.close()

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "ReviveAI Backend API"}
