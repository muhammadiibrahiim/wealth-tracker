"""
Main FastAPI application entry point
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

from database import create_db_and_tables
from routes import assets, wealth, investments, habits, trade
from config import APP_NAME, APP_VERSION

# Import models to register them with SQLModel metadata
from models import (
    Asset,
    AssetValuation,
    Investment,
    InvestmentMetric,
    LifeAspect,
    Habit,
    HabitLog,
    Party,
    CashAccount,
    Item,
    ItemSpecField,
    Trade,
    TradeLine,
    TradeLineSpec,
    TradeLineReceipt,
    TradePayment,
    AccountClass,
    AccountSubClass,
    Account,
    JournalEntry,
    JournalLine,
)

# Initialize FastAPI app
app = FastAPI(title=APP_NAME, version=APP_VERSION)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(assets.router)
app.include_router(wealth.router)
app.include_router(investments.router)
app.include_router(habits.router)
app.include_router(trade.router)


@app.on_event("startup")
def on_startup():
    """Initialize database on startup"""
    create_db_and_tables()


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Redirect to wealth tracker"""
    return RedirectResponse(url="/wealth")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "app": APP_NAME, "version": APP_VERSION}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003, reload=True)
