"""FastAPI web interface for the autonomous support agent."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from support_agent.agent import AgentResponse, run_agent
from support_agent.db_setup import fetch_table, initialize_database
from support_agent.db_runtime import (
    UPLOAD_DB_PATH,
    get_active_database_info,
    use_default_database,
    use_uploaded_database,
    validate_sqlite_database,
)


STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Autonomous Support Agent",
    description="LangGraph support agent with MCP tool access and Langfuse tracing.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    """Incoming chat request payload."""

    message: str = Field(min_length=1, max_length=1_000)


class TableResponse(BaseModel):
    """SQLite table preview response."""

    table: str
    rows: list[dict[str, object]]


class DatabaseInfoResponse(BaseModel):
    """Currently active database metadata."""

    path: str
    name: str
    is_default: bool
    seed_enabled: bool


@app.on_event("startup")
async def startup() -> None:
    """Prepare the local SQLite database before serving requests."""

    await initialize_database()


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the web chat interface."""

    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a simple health check."""

    return {"status": "ok"}


@app.get("/api/database/tables")
async def database_tables() -> dict[str, list[str]]:
    """Return support database tables visible in the UI."""

    return {
        "tables": [
            "tickets",
            "services",
            "incidents",
            "users",
            "devices",
            "knowledge_articles",
        ]
    }


@app.get("/api/database/active", response_model=DatabaseInfoResponse)
async def active_database() -> DatabaseInfoResponse:
    """Return the currently selected support database."""

    return DatabaseInfoResponse(**get_active_database_info())


@app.post("/api/database/default", response_model=DatabaseInfoResponse)
async def select_default_database() -> DatabaseInfoResponse:
    """Switch back to the seeded default support database."""

    info = use_default_database()
    await initialize_database()
    return DatabaseInfoResponse(**info)


@app.post("/api/database/upload", response_model=DatabaseInfoResponse)
async def upload_database(file: UploadFile = File(...)) -> DatabaseInfoResponse:
    """Upload a local SQLite database and switch the app to it."""

    if not file.filename or not file.filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(status_code=400, detail="Upload a .db, .sqlite, or .sqlite3 file.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded database file is empty.")

    UPLOAD_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DB_PATH.write_bytes(content)

    try:
        validate_sqlite_database(UPLOAD_DB_PATH)
    except ValueError as exc:
        UPLOAD_DB_PATH.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    info = use_uploaded_database(UPLOAD_DB_PATH)
    await initialize_database(UPLOAD_DB_PATH)
    return DatabaseInfoResponse(**info)


@app.get("/api/database/{table_name}", response_model=TableResponse)
async def database_table(table_name: str) -> TableResponse:
    """Return a preview of an approved SQLite support table."""

    try:
        return TableResponse(table=table_name, rows=await fetch_table(table_name))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chat", response_model=AgentResponse)
async def chat(payload: ChatRequest) -> AgentResponse:
    """Run the support agent and return the answer with route metadata."""

    try:
        return await run_agent(payload.message)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="The support agent failed to process the request.",
        ) from exc
