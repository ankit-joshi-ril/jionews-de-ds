"""
Smart Analytics Engine router.
Handles chat with Claude using MongoDB analytics tools.
"""

import json
import logging
import time as _time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.claude_client import get_client, get_model, get_conversation, clear_conversation, new_session_id
from services.prompt_builder import build_analytics_prompt
from tools.analytics_tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# IST timezone
_IST = timezone(timedelta(hours=5, minutes=30))


def _build_time_prefix() -> str:
    """Build a compact time-context prefix to inject into every user message."""
    now = int(_time.time())
    now_ist = datetime.now(_IST)
    ist_start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    ist_start_epoch = int(ist_start.timestamp())
    return (
        f"[SYSTEM TIME CONTEXT -- use these values for any date/time query]\n"
        f"Now: {now_ist.strftime('%Y-%m-%d %H:%M:%S')} IST | Epoch: {now} | "
        f"Today(IST) start: {ist_start_epoch} end: {ist_start_epoch + 86400} | "
        f"Last5d: {now - 5*86400} | Last7d: {now - 7*86400} | Last30d: {now - 30*86400}\n"
        f"[END TIME CONTEXT]\n\n"
    )


@router.post("/chat")
async def analytics_chat(request: Request):
    """Handle analytics chat messages with MongoDB tool-use loop."""
    body = await request.json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id", new_session_id())

    if not user_message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    conversation = get_conversation(session_id)

    # Inject real-time context directly into the user message so the model
    # cannot hallucinate wrong dates (e.g. 2024 from training data).
    enriched_message = _build_time_prefix() + user_message
    conversation.append({"role": "user", "content": enriched_message})

    try:
        client = get_client()
        model = get_model()
        system_prompt = build_analytics_prompt()

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=conversation,
        )

        # Tool-use loop (max 5 rounds)
        max_rounds = 5
        tool_round = 0

        while response.stop_reason == "tool_use" and tool_round < max_rounds:
            tool_round += 1
            logger.info(f"Analytics tool round {tool_round}")

            conversation.append({
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            })

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"  Tool: {block.name}")
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })

            conversation.append({"role": "user", "content": tool_results})

            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=conversation,
            )

        # Extract final text
        assistant_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                assistant_text += block.text

        conversation.append({
            "role": "assistant",
            "content": [block.model_dump() for block in response.content],
        })

        return JSONResponse({
            "response": assistant_text,
            "session_id": session_id,
        })

    except Exception as exc:
        logger.exception("Analytics chat error")
        if conversation and conversation[-1]["role"] == "user":
            conversation.pop()
        return JSONResponse(
            {"error": f"Something went wrong: {str(exc)}"},
            status_code=500,
        )


@router.post("/reset")
async def reset_analytics(request: Request):
    """Clear analytics conversation history."""
    body = await request.json()
    session_id = body.get("session_id")
    if session_id:
        clear_conversation(session_id)
    return JSONResponse({"status": "ok"})
