"""MCP server exposing IT support lookups backed by SQLite."""

from __future__ import annotations

from typing import Any

import aiosqlite
from mcp.server.fastmcp import FastMCP

from support_agent.config import get_settings
from support_agent.db_setup import initialize_database


mcp = FastMCP("it_support")


@mcp.tool()
async def get_ticket_status(ticket_id: int) -> dict[str, Any]:
    """Fetch the status and latest note for a support ticket."""

    return await _fetch_one(
        """
        SELECT id, requester_email, subject, category, priority, status,
               assigned_team, created_at, updated_at, latest_note
        FROM tickets
        WHERE id = ?
        """,
        (ticket_id,),
        "ticket",
        f"Ticket #{ticket_id} was not found.",
    )


@mcp.tool()
async def get_service_status(service_name: str) -> dict[str, Any]:
    """Fetch the current operational status for an internal service."""

    normalized = service_name.lower().strip()
    return await _fetch_one(
        """
        SELECT id, name, status, owner_team, region, last_checked, details
        FROM services
        WHERE lower(name) = ?
        """,
        (normalized,),
        "service",
        f"Service '{service_name}' was not found.",
    )


@mcp.tool()
async def search_known_incidents(service_name: str) -> dict[str, Any]:
    """Return known incidents for a given service."""

    settings = get_settings()
    await initialize_database(settings.support_db_path)

    try:
        async with aiosqlite.connect(settings.support_db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, service_name, severity, status, title,
                       started_at, updated_at, summary
                FROM incidents
                WHERE lower(service_name) = ?
                ORDER BY updated_at DESC
                """,
                (service_name.lower().strip(),),
            ) as cursor:
                rows = await cursor.fetchall()

        return {"ok": True, "incidents": [dict(row) for row in rows]}
    except Exception as exc:
        return _database_error(exc)


@mcp.tool()
async def get_user_devices(email: str) -> dict[str, Any]:
    """Return registered endpoint devices for a user email address."""

    settings = get_settings()
    await initialize_database(settings.support_db_path)

    try:
        async with aiosqlite.connect(settings.support_db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, user_email, hostname, os, encryption_status, last_seen, health
                FROM devices
                WHERE lower(user_email) = ?
                ORDER BY last_seen DESC
                """,
                (email.lower().strip(),),
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return {
                "ok": False,
                "error": "DEVICES_NOT_FOUND",
                "message": f"No registered devices were found for {email}.",
            }
        return {"ok": True, "devices": [dict(row) for row in rows]}
    except Exception as exc:
        return _database_error(exc)


async def _fetch_one(
    query: str,
    params: tuple[Any, ...],
    result_key: str,
    not_found_message: str,
) -> dict[str, Any]:
    """Fetch one SQLite row and wrap it in an MCP-friendly payload."""

    settings = get_settings()
    await initialize_database(settings.support_db_path)

    try:
        async with aiosqlite.connect(settings.support_db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return {"ok": False, "error": "NOT_FOUND", "message": not_found_message}
        return {"ok": True, result_key: dict(row)}
    except Exception as exc:
        return _database_error(exc)


def _database_error(exc: Exception) -> dict[str, Any]:
    """Return a stable database error payload."""

    return {
        "ok": False,
        "error": "DATABASE_ERROR",
        "message": "The IT support database is temporarily unavailable.",
        "detail": str(exc),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
