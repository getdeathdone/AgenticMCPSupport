"""LangGraph IT support agent with MCP tool access and Langfuse tracing."""

from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import json
import os
import re
import sys
import time
from enum import StrEnum
from typing import Any, Literal, TypedDict

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langfuse.langchain import CallbackHandler
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from support_agent.config import get_settings
from support_agent.db_setup import initialize_database
from support_agent.knowledge_base import search_knowledge_base


class Route(StrEnum):
    """Supported agent routes."""

    RAG = "rag"
    TOOL = "tool"


class ToolName(StrEnum):
    """Available MCP tool intents."""

    TICKET_STATUS = "get_ticket_status"
    SERVICE_STATUS = "get_service_status"
    KNOWN_INCIDENTS = "search_known_incidents"
    USER_DEVICES = "get_user_devices"


class Classification(BaseModel):
    """Routing decision produced by the classifier node."""

    route: Route
    reason: str
    tool_name: ToolName | None = None
    ticket_id: int | None = None
    service_name: str | None = None
    email: str | None = None


class AgentState(TypedDict, total=False):
    """Shared state passed between LangGraph nodes."""

    user_input: str
    classification: Classification
    tool_result: dict[str, Any]
    rag_source: dict[str, Any]
    answer: str
    source: str
    started_at: float


class AgentResponse(BaseModel):
    """Public response returned by the agent."""

    answer: str
    route: Literal["rag", "tool"]
    latency_ms: int = Field(ge=0)
    source: str
    reason: str


TICKET_PATTERN = re.compile(r"(?:ticket|case|issue)\s*#?\s*(\d{3,})", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
KNOWN_SERVICES = ("vpn", "email", "jira", "payments-api")
TICKET_WORDS = ("ticket", "case", "issue")
SERVICE_STATUS_WORDS = ("down", "status", "outage", "incident", "healthy", "working")
DEVICE_WORDS = ("device", "laptop", "computer", "hostname")
INCIDENT_WORDS = ("incident", "outage")
FUZZY_THRESHOLD = 0.78


def build_langfuse_config() -> RunnableConfig:
    """Create a LangGraph runnable config containing the Langfuse callback handler."""

    settings = get_settings()
    if not (
        settings.langfuse_tracing_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    ):
        return {}

    return {
        "callbacks": [CallbackHandler()],
        "metadata": {
            "service": "autonomous-it-support-agent",
            "component": "langgraph",
        },
        "tags": ["it-support-agent", "langgraph", "mcp", "sqlite"],
    }


async def classify_request(state: AgentState) -> AgentState:
    """Classify the request into knowledge-base retrieval or an MCP tool call."""

    user_input = state["user_input"]
    normalized = user_input.lower()
    terms = _tokenize(user_input)
    ticket_id = _extract_ticket_id(user_input)
    email_match = EMAIL_PATTERN.search(user_input)
    service_name = _extract_service_name(normalized, terms)

    if ticket_id is not None:
        classification = Classification(
            route=Route.TOOL,
            tool_name=ToolName.TICKET_STATUS,
            ticket_id=ticket_id,
            reason="The user asked for the status of a specific support ticket, allowing for minor typos.",
        )
    elif service_name and _contains_fuzzy(terms, SERVICE_STATUS_WORDS):
        classification = Classification(
            route=Route.TOOL,
            tool_name=ToolName.KNOWN_INCIDENTS
            if _contains_fuzzy(terms, INCIDENT_WORDS)
            else ToolName.SERVICE_STATUS,
            service_name=service_name,
            reason="The user asked about a specific IT service state, allowing for minor typos.",
        )
    elif email_match and _contains_fuzzy(terms, DEVICE_WORDS):
        classification = Classification(
            route=Route.TOOL,
            tool_name=ToolName.USER_DEVICES,
            email=email_match.group(0),
            reason="The user asked for endpoint device data tied to a user, allowing for minor typos.",
        )
    else:
        classification = Classification(
            route=Route.RAG,
            reason="The user asked a troubleshooting or how-to question for the knowledge base.",
        )

    return {"classification": classification}


async def knowledge_base_node(state: AgentState) -> AgentState:
    """Retrieve a matching support document, falling back to SQLite articles."""

    document = search_knowledge_base(state["user_input"])
    if document is not None:
        return {
            "rag_source": {
                "title": document.title,
                "source": document.source,
                "content": document.content,
            },
            "answer": f"{document.title}: {document.content}",
            "source": f"Markdown knowledge base: {document.source}",
        }

    article = await _find_knowledge_article(state["user_input"])
    if article is None:
        return {
            "answer": (
                "I could not find a precise runbook for that issue. Please include the "
                "affected service, error message, and user email so I can route it."
            ),
            "source": "SQLite table: knowledge_articles",
        }

    return {
        "rag_source": article,
        "answer": f"{article['title']}: {article['content']}",
        "source": f"SQLite table: knowledge_articles, article #{article['id']}",
    }


async def call_support_tool_node(state: AgentState) -> AgentState:
    """Call the local MCP support server and store the tool response."""

    classification = state["classification"]
    if classification.tool_name is None:
        return {"tool_result": _tool_error("No MCP tool was selected.")}

    settings = get_settings()
    await initialize_database(settings.support_db_path)

    client = MultiServerMCPClient(
        {
            "it_support": {
                "command": sys.executable,
                "args": ["-m", "support_agent.mcp_server"],
                "transport": "stdio",
                "env": {
                    **os.environ,
                    "SUPPORT_DB_PATH": str(settings.support_db_path),
                    "PYTHONPATH": os.environ.get("PYTHONPATH", "src"),
                },
            }
        }
    )

    try:
        tools = await client.get_tools()
        selected_tool = next(tool for tool in tools if tool.name == classification.tool_name)
        raw_result = await selected_tool.ainvoke(_tool_args(classification))
        result = _coerce_tool_result(raw_result)
        return {
            "tool_result": result,
            "source": f"MCP tool: {classification.tool_name}; SQLite support database",
        }
    except Exception as exc:
        return {"tool_result": _tool_error("The IT support MCP tool is temporarily unavailable.", exc)}


async def tool_fallback_node(state: AgentState) -> AgentState:
    """Convert MCP or database failures into a graceful user-facing response."""

    result = state.get("tool_result", {})
    message = result.get("message") or "I could not retrieve that IT support record right now."
    return {
        "answer": f"{message} Please retry or escalate to the service desk with the exact ticket, service, or user email.",
        "source": state.get("source", "MCP tool fallback"),
    }


async def format_tool_response_node(state: AgentState) -> AgentState:
    """Format a successful MCP tool response for the user."""

    classification = state["classification"]
    result = state["tool_result"]

    if classification.tool_name == ToolName.TICKET_STATUS:
        ticket = result["ticket"]
        answer = (
            f"Ticket #{ticket['id']} is {ticket['status'].replace('_', ' ')}. "
            f"Priority: {ticket['priority']}. Assigned team: {ticket['assigned_team']}. "
            f"Latest note: {ticket['latest_note']}"
        )
    elif classification.tool_name == ToolName.SERVICE_STATUS:
        service = result["service"]
        answer = (
            f"{service['name']} is {service['status'].replace('_', ' ')}. "
            f"Owner: {service['owner_team']}. Region: {service['region']}. "
            f"Details: {service['details']}"
        )
    elif classification.tool_name == ToolName.KNOWN_INCIDENTS:
        incidents = result.get("incidents", [])
        if not incidents:
            answer = "No known incidents are currently recorded for that service."
        else:
            incident = incidents[0]
            answer = (
                f"Known incident #{incident['id']}: {incident['title']} "
                f"({incident['severity']}, {incident['status']}). {incident['summary']}"
            )
    elif classification.tool_name == ToolName.USER_DEVICES:
        devices = result["devices"]
        device_summaries = [
            f"{device['hostname']} ({device['os']}, health: {device['health']})"
            for device in devices
        ]
        answer = "Registered devices: " + "; ".join(device_summaries)
    else:
        answer = "The selected support tool completed successfully."

    return {"answer": answer, "source": state.get("source", "MCP tool")}


def route_after_classification(state: AgentState) -> Literal["rag", "tool"]:
    """Select the next node after classification."""

    return state["classification"].route.value


def route_after_tool(state: AgentState) -> Literal["format_tool", "fallback"]:
    """Select normal formatting or fallback after the MCP tool call."""

    result = state.get("tool_result", {})
    return "format_tool" if result.get("ok") is True else "fallback"


def _extract_service_name(normalized_input: str, terms: set[str]) -> str | None:
    """Extract a known service name from user input, allowing minor typos."""

    for service_name in KNOWN_SERVICES:
        if service_name in normalized_input:
            return service_name
        if _contains_fuzzy(terms, (service_name,)):
            return service_name
    return None


def _extract_ticket_id(user_input: str) -> int | None:
    """Extract a ticket id even when the ticket keyword contains a typo."""

    direct_match = TICKET_PATTERN.search(user_input)
    if direct_match:
        return int(direct_match.group(1))

    tokens = re.findall(r"[a-zA-Z]+|#?\d{3,}", user_input.lower())
    for index, token in enumerate(tokens[:-1]):
        if _is_fuzzy_match(token, TICKET_WORDS):
            id_match = re.search(r"\d{3,}", tokens[index + 1])
            if id_match:
                return int(id_match.group(0))
    return None


def _tokenize(text: str) -> set[str]:
    """Tokenize user input for fuzzy matching."""

    return {term for term in re.findall(r"[a-z0-9-]+", text.lower()) if len(term) > 1}


def _contains_fuzzy(terms: set[str], candidates: tuple[str, ...]) -> bool:
    """Return whether any term approximately matches a candidate."""

    return any(_is_fuzzy_match(term, candidates) for term in terms)


def _is_fuzzy_match(term: str, candidates: tuple[str, ...]) -> bool:
    """Return whether a token is close enough to one of the expected words."""

    for candidate in candidates:
        if term == candidate or candidate in term or term in candidate:
            return True
        if SequenceMatcher(None, term, candidate).ratio() >= FUZZY_THRESHOLD:
            return True
    return False


async def _find_knowledge_article(user_input: str) -> dict[str, Any] | None:
    """Find the most relevant knowledge article with simple keyword scoring."""

    await initialize_database()
    terms = {term for term in _tokenize(user_input) if len(term) > 2}
    async with aiosqlite.connect(get_settings().support_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, title, category, keywords, content, updated_at FROM knowledge_articles"
        ) as cursor:
            rows = await cursor.fetchall()

    best_row: aiosqlite.Row | None = None
    best_score = 0
    for row in rows:
        searchable = set(row["keywords"].lower().replace(",", " ").split())
        searchable.update(row["title"].lower().split())
        score = len(terms.intersection(searchable))
        score += sum(1 for term in terms if _contains_fuzzy(searchable, (term,)))
        if score > best_score:
            best_score = score
            best_row = row

    return dict(best_row) if best_row is not None and best_score > 0 else None


def _tool_args(classification: Classification) -> dict[str, Any]:
    """Build MCP tool arguments from the classification result."""

    if classification.tool_name == ToolName.TICKET_STATUS:
        return {"ticket_id": classification.ticket_id}
    if classification.tool_name in {ToolName.SERVICE_STATUS, ToolName.KNOWN_INCIDENTS}:
        return {"service_name": classification.service_name}
    if classification.tool_name == ToolName.USER_DEVICES:
        return {"email": classification.email}
    return {}


def _tool_error(message: str, exc: Exception | None = None) -> dict[str, Any]:
    """Return a stable MCP failure payload."""

    payload: dict[str, Any] = {"ok": False, "error": "MCP_TOOL_ERROR", "message": message}
    if exc is not None:
        payload["detail"] = str(exc)
    return payload


def _coerce_tool_result(raw_result: Any) -> dict[str, Any]:
    """Normalize MCP tool output into a dictionary."""

    if isinstance(raw_result, dict):
        return raw_result
    if isinstance(raw_result, list) and raw_result:
        first_item = raw_result[0]
        if isinstance(first_item, dict) and "text" in first_item:
            return json.loads(first_item["text"])
    if isinstance(raw_result, str):
        return json.loads(raw_result)
    if hasattr(raw_result, "content"):
        content = raw_result.content
        if content and hasattr(content[0], "text"):
            return json.loads(content[0].text)
    raise TypeError(f"Unsupported MCP tool result type: {type(raw_result)!r}")


def build_graph() -> Any:
    """Build and compile the LangGraph workflow."""

    graph = StateGraph(AgentState)
    graph.add_node("classify", classify_request)
    graph.add_node("rag", knowledge_base_node)
    graph.add_node("tool", call_support_tool_node)
    graph.add_node("format_tool", format_tool_response_node)
    graph.add_node("fallback", tool_fallback_node)

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        route_after_classification,
        {"rag": "rag", "tool": "tool"},
    )
    graph.add_conditional_edges(
        "tool",
        route_after_tool,
        {"format_tool": "format_tool", "fallback": "fallback"},
    )
    graph.add_edge("rag", END)
    graph.add_edge("format_tool", END)
    graph.add_edge("fallback", END)

    return graph.compile()


async def run_agent(user_input: str) -> AgentResponse:
    """Run the IT support agent for a single user input."""

    started_at = time.perf_counter()
    app = build_graph()
    result = await app.ainvoke(
        {"user_input": user_input, "started_at": started_at},
        config=build_langfuse_config(),
    )
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    classification = result["classification"]
    return AgentResponse(
        answer=result["answer"],
        route=classification.route.value,
        latency_ms=latency_ms,
        source=result.get("source", "unknown"),
        reason=classification.reason,
    )


async def _demo() -> None:
    """Run a small local demo when invoked as a module."""

    examples = [
        "How do I troubleshoot VPN login?",
        "What is the status of ticket #2041?",
        "Is Jira down right now?",
        "Show devices for grace@example.com",
    ]
    for example in examples:
        response = await run_agent(example)
        print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(_demo())
