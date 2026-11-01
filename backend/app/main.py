from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from app.database.base import Base
from app.database.session import engine
from app.database.migrations import apply_additive_migrations
from app.api.v1.routes import router
from app.core.config import settings
import app.models.entities

def create_app():
    app=FastAPI(title="AI Agent Evaluation Platform",version="0.1.0",openapi_url="/api/openapi.json",docs_url="/api/docs",redoc_url="/api/redoc")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))
    app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_methods=["GET","POST","PATCH","DELETE"],allow_headers=["*"])
    @app.exception_handler(HTTPException)
    async def http_error(_,exc):
        detail=exc.detail if isinstance(exc.detail,dict) else {"code":"HTTP_ERROR","message":str(exc.detail)}
        return JSONResponse(status_code=exc.status_code,content={"error":detail})
    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc: RequestValidationError):
        formatted = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', []) if p != 'body')}: {err.get('msg', 'invalid')}"
            for err in exc.errors()
        )
        safe_errors = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": formatted or "Request validation failed",
                    "details": safe_errors,
                },
                "detail": safe_errors,
            },
        )
    @app.on_event("startup")
    def init_db():
        Base.metadata.create_all(engine)
        apply_additive_migrations(engine)
    app.include_router(router,prefix="/api")
    return app
app=create_app()
