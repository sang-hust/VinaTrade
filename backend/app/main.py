import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import admin, ai, alerts, auth, insights, market, me, portfolios, risk, screener, system, watchlists
from app.core.config import settings
from app.core.errors import ApiError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("vinatrade")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.tasks import scheduler

    scheduler.start()
    yield
    if scheduler.scheduler.running:
        scheduler.scheduler.shutdown(wait=False)


app = FastAPI(title="Vinatrade API", version="0.1.0", lifespan=lifespan, docs_url="/docs" if settings.debug else None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list or ["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

API = "/api/v1"
for r in (auth.router, me.router, market.router, insights.router, screener.router, alerts.router, watchlists.router, portfolios.router, risk.router, ai.router, admin.router, system.router):
    app.include_router(r, prefix=API)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errs = exc.errors()
    first = errs[0] if errs else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION", "message": f"Dữ liệu không hợp lệ: {loc} {first.get('msg', '')}".strip(), "details": {"errors": errs[:10]}}})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL", "message": "Có lỗi xảy ra, hãy thử lại sau", "details": {}}})


@app.get("/")
async def root():
    return {"app": settings.app_name, "docs": "/docs" if settings.debug else None, "health": f"{API}/health"}
