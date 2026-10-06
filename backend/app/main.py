"""
main.py — FastAPI application entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_agent import router as agent_router
from app.api.routes_queue import router as queue_router

app = FastAPI(
    title="SwasthiQ Clinic Front Desk Agent",
    description="AI-powered clinic front desk for Sunrise Clinic, Dehradun.",
    version="1.0.0",
)

# Allow the React frontend on any port during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_router)
app.include_router(queue_router)


@app.get("/health")
def health():
    return {"status": "ok"}
