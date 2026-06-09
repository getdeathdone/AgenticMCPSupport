"""Create and seed the local SQLite IT support database."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite

from support_agent.config import get_settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    department TEXT NOT NULL,
    role TEXT NOT NULL,
    location TEXT NOT NULL,
    support_tier TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    user_email TEXT NOT NULL,
    hostname TEXT NOT NULL,
    os TEXT NOT NULL,
    encryption_status TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    health TEXT NOT NULL,
    FOREIGN KEY(user_email) REFERENCES users(email)
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    owner_team TEXT NOT NULL,
    region TEXT NOT NULL,
    last_checked TEXT NOT NULL,
    details TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY,
    service_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    FOREIGN KEY(service_name) REFERENCES services(name)
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    requester_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    assigned_team TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    latest_note TEXT NOT NULL,
    FOREIGN KEY(requester_email) REFERENCES users(email)
);

CREATE TABLE IF NOT EXISTS knowledge_articles (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    keywords TEXT NOT NULL,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


SEED_USERS = (
    (1, "Ada Lovelace", "ada@example.com", "Engineering", "Backend Engineer", "London", "standard"),
    (2, "Grace Hopper", "grace@example.com", "Finance", "Finance Manager", "New York", "priority"),
    (3, "Alan Turing", "alan@example.com", "Security", "Security Analyst", "Warsaw", "standard"),
)

SEED_DEVICES = (
    (1, "ada@example.com", "LON-MBP-042", "macOS 15.4", "enabled", "2026-06-09 08:10 UTC", "healthy"),
    (2, "grace@example.com", "NYC-LTP-118", "Windows 11", "enabled", "2026-06-09 07:44 UTC", "warning: pending reboot"),
    (3, "alan@example.com", "WAW-LNX-007", "Ubuntu 24.04", "enabled", "2026-06-09 08:01 UTC", "healthy"),
)

SEED_SERVICES = (
    (1, "vpn", "degraded", "Infrastructure", "global", "2026-06-09 08:30 UTC", "Elevated authentication latency for EU users."),
    (2, "email", "operational", "Collaboration", "global", "2026-06-09 08:28 UTC", "Mail flow and calendar sync are healthy."),
    (3, "jira", "partial_outage", "Platform", "eu-west", "2026-06-09 08:31 UTC", "Issue search is slow; ticket creation is available."),
    (4, "payments-api", "operational", "SRE", "us-east", "2026-06-09 08:27 UTC", "No active alerts."),
)

SEED_INCIDENTS = (
    (3001, "vpn", "sev2", "investigating", "VPN login failures in EU", "2026-06-09 07:55 UTC", "2026-06-09 08:25 UTC", "SAML auth requests intermittently time out for EU users."),
    (3002, "jira", "sev3", "monitoring", "Jira search latency", "2026-06-09 06:40 UTC", "2026-06-09 08:10 UTC", "Search index lag increased after scheduled maintenance."),
)

SEED_TICKETS = (
    (2041, "ada@example.com", "Cannot connect to VPN", "vpn", "high", "in_progress", "Infrastructure", "2026-06-09 07:58 UTC", "2026-06-09 08:20 UTC", "User is affected by active VPN incident 3001."),
    (2042, "grace@example.com", "Laptop slow after update", "device", "medium", "waiting_on_user", "Endpoint Support", "2026-06-08 15:10 UTC", "2026-06-09 07:30 UTC", "Requested reboot and diagnostic log upload."),
    (2043, "alan@example.com", "Need access to security dashboard", "access", "low", "resolved", "IAM", "2026-06-07 10:05 UTC", "2026-06-07 12:45 UTC", "Access granted through group sec-dashboard-readers."),
)

SEED_ARTICLES = (
    (
        101,
        "VPN troubleshooting runbook",
        "vpn",
        "vpn,connect,connection,saml,login,mfa,timeout",
        "Check the service status first. If VPN is degraded, tell the user there is a known incident. If there is no incident, ask them to confirm MFA, restart the VPN client, and retry on another network.",
        "2026-06-01",
    ),
    (
        102,
        "Password reset policy",
        "access",
        "password,reset,login,locked,mfa,account",
        "Users can reset passwords through the identity portal. After three failed MFA attempts, the account is temporarily locked for 15 minutes.",
        "2026-05-20",
    ),
    (
        103,
        "Email troubleshooting guide",
        "email",
        "email,outlook,mail,calendar,sync",
        "For email issues, check service health, verify network connectivity, restart the mail client, and confirm the mailbox is not over quota.",
        "2026-05-29",
    ),
    (
        104,
        "Device performance checklist",
        "device",
        "laptop,slow,performance,cpu,memory,reboot",
        "For slow laptops, check pending reboot status, disk space, endpoint health, and recent security scans before escalating.",
        "2026-06-03",
    ),
)


async def initialize_database(db_path: Path | None = None) -> None:
    """Create all IT support tables and insert deterministic demo data."""

    settings = get_settings()
    target = db_path or settings.support_db_path
    target.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(target) as db:
        await db.executescript(SCHEMA_SQL)
        if settings.support_db_seed_enabled:
            await _upsert_many(db, "users", SEED_USERS)
            await _upsert_many(db, "devices", SEED_DEVICES)
            await _upsert_many(db, "services", SEED_SERVICES)
            await _upsert_many(db, "incidents", SEED_INCIDENTS)
            await _upsert_many(db, "tickets", SEED_TICKETS)
            await _upsert_many(db, "knowledge_articles", SEED_ARTICLES)
        await db.commit()


async def fetch_table(table_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch rows from an approved support database table."""

    allowed_tables = {
        "users",
        "devices",
        "services",
        "incidents",
        "tickets",
        "knowledge_articles",
    }
    if table_name not in allowed_tables:
        raise ValueError(f"Unsupported table: {table_name}")

    await initialize_database()
    async with aiosqlite.connect(get_settings().support_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,)) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def _upsert_many(
    db: aiosqlite.Connection,
    table: str,
    rows: tuple[tuple[Any, ...], ...],
) -> None:
    """Replace deterministic seed rows without disturbing unrelated user data."""

    if not rows:
        return
    placeholders = ", ".join("?" for _ in rows[0])
    await db.executemany(f"INSERT OR REPLACE INTO {table} VALUES ({placeholders})", rows)


def main() -> None:
    """Initialize the database from the command line."""

    asyncio.run(initialize_database())


if __name__ == "__main__":
    main()
