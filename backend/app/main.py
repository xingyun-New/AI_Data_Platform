"""FastAPI application entry-point."""

import logging
from sqlalchemy import text

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import AuditLogMiddleware
from app.api.routes import auth, batch, documents, graph, index_rules, prompts, rules, settings, users
from app.database import Base, engine, run_migrations
from app.models import knowledge_graph as _kg_models  # noqa: F401  ensure tables are registered
from app.models import department as _department_model  # noqa: F401  register departments table
from app.models import user_role as _user_role_model  # noqa: F401  register user_roles table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)

Base.metadata.create_all(bind=engine)
run_migrations()

app = FastAPI(
    title="AI Data Platform",
    description="AI 驱动的文档脱敏与索引管理平台",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(AuditLogMiddleware)

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(documents.router, prefix="/api/documents", tags=["文档"])
app.include_router(rules.router, prefix="/api/rules", tags=["脱敏规则"])
app.include_router(index_rules.router, prefix="/api/index-rules", tags=["索引规则"])
app.include_router(batch.router, prefix="/api/batch", tags=["Batch"])
app.include_router(prompts.router, prefix="/api/prompts", tags=["提示词"])
app.include_router(settings.router, prefix="/api", tags=["系统设置"])
app.include_router(graph.router, prefix="/api/graph", tags=["知识图谱"])
app.include_router(users.router, prefix="/api", tags=["用户管理"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler that returns consistent JSON error responses."""
    logger = logging.getLogger("app.error_handler")
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误",
            "error_type": type(exc).__name__,
        },
    )


@app.get("/health", tags=["系统"])
def health():
    """Health check with database connectivity verification."""
    result = {"status": "ok", "services": {}}
    
    # Check database connectivity
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        result["services"]["database"] = "healthy"
    except Exception as e:
        result["status"] = "degraded"
        result["services"]["database"] = f"unhealthy: {str(e)}"
    
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
