"""Database-backed tool-calling agent for a fictional PC workshop.

The language model chooses tools; Python owns the SQLite queries and arithmetic.
No customer-facing price or policy is supplied from model memory.
"""

import csv
import json
import os
import re
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "byteforge.db"
load_dotenv(ROOT / ".env")
MAX_STEPS = 6


def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def build_database():
    """Recreate both SQLite tables from the submitted CSV files at startup."""
    with (ROOT / "shop_info.csv").open(newline="", encoding="utf-8-sig") as file:
        info_rows = list(csv.DictReader(file))
    with (ROOT / "catalog.csv").open(newline="", encoding="utf-8-sig") as file:
        catalog_rows = list(csv.DictReader(file))
    if len(info_rows) < 8 or len(catalog_rows) < 15:
        raise ValueError("The homework requires at least 8 topics and 15 records.")
    with connect() as connection:
        connection.execute("DROP TABLE IF EXISTS shop_info")
        connection.execute("DROP TABLE IF EXISTS catalog")
        connection.execute(
            "CREATE TABLE shop_info (topic TEXT PRIMARY KEY, content TEXT NOT NULL)"
        )
        connection.execute(
            """CREATE TABLE catalog (
                item_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                name_zh TEXT NOT NULL,
                category TEXT NOT NULL,
                price INTEGER NOT NULL CHECK(price >= 0),
                available INTEGER NOT NULL CHECK(available IN (0, 1))
            )"""
        )
        connection.executemany(
            "INSERT INTO shop_info (topic, content) VALUES (?, ?)",
            [(row["topic"], row["content"]) for row in info_rows],
        )
        connection.executemany(
            """INSERT INTO catalog
               (item_id, name, name_zh, category, price, available)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    int(row["item_id"]),
                    row["name"],
                    row["name_zh"],
                    row["category"],
                    int(row["price"]),
                    int(row["available"]),
                )
                for row in catalog_rows
            ],
        )
    return len(info_rows), len(catalog_rows)


def available_topics():
    with connect() as connection:
        return [
            row["topic"]
            for row in connection.execute("SELECT topic FROM shop_info ORDER BY topic")
        ]


def get_shop_info(topic):
    """Return data for one policy or store-information topic."""
    with connect() as connection:
        row = connection.execute(
            "SELECT topic, content FROM shop_info WHERE topic = ?", (topic,)
        ).fetchone()
    if row is None:
        return {"found": False, "topics_available": available_topics()}
    return {"found": True, "topic": row["topic"], "content": row["content"]}


def find_catalog(query):
    """Search the submitted service and part records by English or Chinese name."""
    query = str(query).strip()
    if not query:
        return {"found": False, "reason": "empty_query"}
    if re.search(r"\bdiagnostics?\b", query, re.IGNORECASE):
        query = re.sub(r"\bdiagnostics?\b", "diagnosis", query, flags=re.IGNORECASE)
    if re.search(r"\bRAM\b", query, re.IGNORECASE) and re.search(
        r"\b(repair|upgrade)\b", query, re.IGNORECASE
    ):
        query = "RAM installation"
    with connect() as connection:
        rows = connection.execute(
            """SELECT name, name_zh, category, price, available FROM catalog
               WHERE instr(lower(name), lower(?)) > 0 OR instr(name_zh, ?) > 0
               ORDER BY category, name LIMIT 12""",
            (query, query),
        ).fetchall()
    if not rows:
        return {"found": False, "query": query, "items": []}
    return {
        "found": True,
        "items": [
            {
                "name": row["name"],
                "name_zh": row["name_zh"],
                "category": row["category"],
                "price": row["price"],
                "available": bool(row["available"]),
            }
            for row in rows
        ],
    }


def _exact_catalog_item(name):
    with connect() as connection:
        return connection.execute(
            """SELECT name, name_zh, category, price, available FROM catalog
               WHERE lower(name) = lower(?) OR name_zh = ?""",
            (name.strip(), name.strip()),
        ).fetchone()


def calculate_repair_quote(labor_service="none", device_type=None, part_name="none"):
    """Compute two repair outcomes using only catalog prices, never model arithmetic.

    If repair is approved, the diagnostic fee is credited and the customer pays
    labor plus the listed part. If repair is declined, only diagnosis is charged.
    This is an estimate, not a diagnosis or compatibility guarantee.
    """
    if device_type not in {"desktop", "laptop"}:
        return {"found": False, "reason": "device_type_must_be_desktop_or_laptop"}
    diagnostic_name = "Desktop diagnosis" if device_type == "desktop" else "Laptop diagnosis"
    diagnostic = _exact_catalog_item(diagnostic_name)
    if diagnostic is None or not diagnostic["available"]:
        return {"found": False, "reason": "diagnostic_service_unavailable"}
    if not labor_service or str(labor_service).lower() == "none":
        return {
            "found": True,
            "currency": "TWD",
            "device_type": device_type,
            "labor_service": None,
            "labor_fee": None,
            "part": None,
            "part_price": None,
            "diagnostic_fee": diagnostic["price"],
            "if_repair_approved_total": None,
            "if_repair_declined_total": diagnostic["price"],
            "note": "Declined repair: only the diagnostic fee is due; no approved-repair quote was requested.",
        }
    labor = _exact_catalog_item(labor_service)
    if labor is None or labor["category"] != "service":
        return {"found": False, "reason": "labor_service_not_found"}
    if not labor["available"]:
        return {"found": False, "reason": "labor_service_unavailable"}
    part = None
    if part_name and part_name.lower() != "none":
        part = _exact_catalog_item(part_name)
        if part is None or part["category"] != "part":
            return {"found": False, "reason": "part_not_found"}
        if not part["available"]:
            return {"found": False, "reason": "part_unavailable"}
    part_price = part["price"] if part is not None else 0
    return {
        "found": True,
        "currency": "TWD",
        "device_type": device_type,
        "labor_service": labor["name"],
        "labor_fee": labor["price"],
        "part": part["name"] if part is not None else None,
        "part_price": part_price,
        "diagnostic_fee": diagnostic["price"],
        "if_repair_approved_total": labor["price"] + part_price,
        "if_repair_declined_total": diagnostic["price"],
        "diagnostic_credit_policy": "The diagnostic fee is credited toward approved repair.",
        "note": "Estimate only; a technician must confirm fault, part compatibility, and final quote.",
    }


def transfer_to_human(reason):
    """Return a simulated hand-over route; no real message is sent."""
    contact = get_shop_info("contact")
    return {
        "handover_requested": True,
        "reason": str(reason)[:160],
        "contact": contact["content"] if contact["found"] else "Contact unavailable.",
        "action": "Ask the customer to contact the technician desk; do not claim a booking or direct transfer.",
    }


TOOL_FUNCTIONS = {
    "get_shop_info": get_shop_info,
    "find_catalog": find_catalog,
    "calculate_repair_quote": calculate_repair_quote,
    "transfer_to_human": transfer_to_human,
}


def tool_specs():
    return [
        {
            "type": "function",
            "function": {
                "name": "get_shop_info",
                "description": (
                    "Look up ByteForge policies and store facts: hours, location, contact, "
                    "appointments, diagnosis policy, assembly, customer parts, turnaround, payment, "
                    "warranty, backups, or parking. Use this for factual shop-policy questions, "
                    "not amounts owed after a repair is approved or declined, and not requests "
                    "for a person's private contact details."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "enum": available_topics()}
                    },
                    "required": ["topic"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_catalog",
                "description": (
                    "Search the catalog of PC assembly, repair, upgrade and part records. "
                    "Use for prices, availability and service names. Search before quoting "
                    "if an item name is ambiguous."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calculate_repair_quote",
                "description": (
                    "Calculate a desktop or laptop repair estimate from exact catalog items. "
                    "Use whenever the customer asks for any amount owed after a repair is "
                    "approved or declined. For a declined repair, supply device_type and omit "
                    "labor_service; this returns the diagnostic-only fee. "
                    "Never calculate prices in the model. "
                    "If a name is unclear, find_catalog first."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "labor_service": {
                            "type": "string",
                            "description": "Exact catalog service name for an approved repair; omit for a declined-only diagnostic quote.",
                        },
                        "device_type": {
                            "type": "string",
                            "enum": ["desktop", "laptop"],
                        },
                        "part_name": {
                            "type": "string",
                            "description": "Exact catalog part name, or 'none'.",
                        },
                    },
                    "required": ["device_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "transfer_to_human",
                "description": (
                    "Use for complaints, a request for a technician, uncertain compatibility, "
                    "a specific diagnosis, a person's private or unlisted direct contact details, "
                    "or shop questions that the data cannot answer. "
                    "This returns a simulated contact route; it does not send a message."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                    "required": ["reason"],
                },
            },
        },
    ]


SYSTEM_PROMPT = """You are the customer service agent for ByteForge PC Workshop,
a fictional computer assembly and repair shop created for a course project.
All prices are in New Taiwan dollars. Never imply this is a real operating business.

GROUNDING
- Answer shop facts, service prices and estimates only from tool results, never memory.
- If a result says not found or unavailable, say so; never invent a price, policy or stock.
- The catalog is a demo. Do not diagnose hardware or guarantee compatibility or repair time.

SCOPE
- Discuss only this workshop. Politely decline unrelated requests and return to workshop topics.

ROUTING
- Shop policy and listed public contact questions: get_shop_info.
- Service, part, price and availability questions: find_catalog.
- Any amount owed after approving or declining a repair, including a diagnostic-only fee:
  calculate_repair_quote. Never take a fee from policy text or do price arithmetic yourself.
- For a declined repair, call calculate_repair_quote with device_type only; do not search the
  catalog first. The tool returns the diagnostic-only amount owed.
- Complaints, unknown shop-specific facts, actual fault diagnosis, uncertain compatibility,
  a person's private or unlisted direct contact details, or requests for a technician:
  transfer_to_human. Do not substitute general shop contact lookup for this handover.
- For an ambiguous service or part name, search first and ask the customer to clarify.

LANGUAGE AND FORMAT
- Reply in the customer's language, Traditional Chinese or English.
- Be polite and concise, usually no more than three sentences.
- Do not claim a booking, a real hand-over, or that a technician has been contacted.
"""


def _client_from_env():
    url = os.getenv("LLM_API_URL", "").strip()
    model = os.getenv("MODEL_NAME", "").strip()
    key = os.getenv("API_KEY", "").strip()
    if not url or not model or not key:
        raise RuntimeError("Set LLM_API_URL, MODEL_NAME and API_KEY in the local .env file.")
    return OpenAI(api_key=key, base_url=url, timeout=60.0), model


def _messages_from_history(chat_history):
    if not chat_history or chat_history[-1].get("role") != "user":
        raise ValueError("The last chat message must be a customer question.")
    history = [
        {"role": entry["role"], "content": entry["content"]}
        for entry in chat_history[-12:]
        if entry.get("role") in {"user", "assistant"}
        and isinstance(entry.get("content"), str)
    ]
    question = history[-1]["content"]
    language = "Traditional Chinese" if re.search(r"[一-鿿]", question) else "English"
    return (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history[:-1]
        + [{"role": "system", "content": f"Reply in {language}."}]
        + history[-1:]
    )


def run_agent(chat_history, api_client=None, model_name=None):
    """Return (answer, visible tool trace) for the final customer turn."""
    messages = _messages_from_history(chat_history)
    if api_client is None:
        api_client, configured_model = _client_from_env()
        model_name = model_name or configured_model
    model_name = model_name or "test-model"
    trace = []
    for step in range(1, MAX_STEPS + 1):
        response = api_client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tool_specs(),
            temperature=0.2,
        )
        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            return (message.content or "").strip(), trace
        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in calls
                ],
            }
        )
        for call in calls:
            name = call.function.name
            try:
                arguments = json.loads(call.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object.")
                if name not in TOOL_FUNCTIONS:
                    result = {"error": "unknown_tool", "name": name}
                else:
                    result = TOOL_FUNCTIONS[name](**arguments)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                arguments = call.function.arguments
                result = {"error": "invalid_arguments", "detail": str(error)[:160]}
            trace.append(
                {"step": step, "tool": name, "arguments": arguments, "result": result}
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    return (
        "Sorry, I could not finish safely. Please contact the technician desk.",
        trace,
    )

