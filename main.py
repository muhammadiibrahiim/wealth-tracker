"""
Main FastAPI application entry point
"""
from fastapi import FastAPI, Request, Response
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


def _tighten_whitespace(img, blank_thresh=245, max_gap=56, pad=28):
    """Collapse tall blank bands (page margins, gaps before footers) so the
    document reads like an image, not a page scan. Keeps small gaps as-is.

    A row is blank only if it has NO dark pixel — judged by the row minimum,
    which tolerates non-white page backgrounds. Row minima are computed by
    repeatedly folding the image in half through a darker() merge.
    """
    from PIL import Image, ImageChops
    h = img.height
    g = img.convert("L")
    w = g.width
    while w > 1:
        half = (w + 1) // 2
        left = g.crop((0, 0, half, h))
        right = g.crop((w - half, 0, w, h))
        g = ImageChops.darker(left, right)
        w = half
    row_mins = list(g.getdata())
    is_content = [m < blank_thresh for m in row_mins]
    segments = []
    start = None
    for y, c in enumerate(is_content):
        if c and start is None:
            start = y
        elif not c and start is not None:
            segments.append((start, y))
            start = None
    if start is not None:
        segments.append((start, h))
    if not segments:
        return img
    pieces = []
    prev_end = None
    for s, e in segments:
        gap = pad if prev_end is None else min(s - prev_end, max_gap)
        pieces.append((s, e, gap))
        prev_end = e
    out_h = sum((e - s) + g for s, e, g in pieces) + pad
    # Fill with the document's actual background color (sampled from a blank
    # row) so inserted gaps don't show as lighter seams.
    bg = "white"
    first_blank = next((y for y, c in enumerate(is_content) if not c), None)
    if first_blank is not None:
        bg = img.getpixel((img.width // 2, first_blank))
    out = Image.new("RGB", (img.width, out_h), bg)
    y = 0
    for s, e, g in pieces:
        y += g
        out.paste(img.crop((0, s, img.width, e)), (0, y))
        y += e - s
    return out


@app.middleware("http")
async def pdf_as_image(request: Request, call_next):
    """Any PDF endpoint opened with ?img=1 returns a PNG render instead —
    lets documents be viewed/copied as images straight from the browser."""
    response = await call_next(request)
    if (
        request.query_params.get("img") == "1"
        and response.headers.get("content-type", "").startswith("application/pdf")
    ):
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        import io
        import pypdfium2 as pdfium
        from PIL import Image
        doc = pdfium.PdfDocument(body)
        pages = [p.render(scale=4).to_pil() for p in doc]
        if len(pages) == 1:
            img = pages[0]
        else:
            # Stack multi-page docs into one tall image.
            width = max(p.width for p in pages)
            img = Image.new("RGB", (width, sum(p.height for p in pages)), "white")
            y = 0
            for p in pages:
                img.paste(p, (0, y))
                y += p.height
        # Snap near-white tints to pure white — removes faint banding the
        # renderer produces and gives a clean background for chat apps.
        img = img.point(lambda v: 255 if v >= 248 else v)
        img = _tighten_whitespace(img)
        # Rendered at 4x for crisp glyphs; downscale to a compact
        # chat-friendly size (the supersampling keeps text sharp).
        target_w = 1200
        if img.width > target_w:
            img = img.resize(
                (target_w, round(img.height * target_w / img.width)),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
    return response


@app.on_event("startup")
def on_startup():
    """Initialize database + seed default chart of accounts on startup.

    Fresh installs (shared users) hit Record Cost / other flows expecting
    Capital A/C, Profit / Loss A/C etc. before ever visiting Chart of A/Cs,
    which used to be the only path that seeded them. Seed here so the app
    is usable end-to-end on first launch.
    """
    create_db_and_tables()
    try:
        from database import engine
        from sqlmodel import Session
        from services import account_setup
        from config import DEFAULT_USER_ID
        with Session(engine) as s:
            account_setup.seed_chart_of_accounts(s, DEFAULT_USER_ID)
            s.commit()
    except Exception as e:
        # Non-fatal: startup should still succeed even if seeding fails
        # (e.g. race with a migration). User can still trigger the seed by
        # visiting /trade/coa.
        import logging
        logging.getLogger("uvicorn").warning(f"COA seed on startup failed: {e}")


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
