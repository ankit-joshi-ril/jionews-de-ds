"""
Publisher Onboarding router.
Handles chat with Claude using onboarding tools + conversation management.
"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.claude_client import get_client, get_model, get_conversation, clear_conversation, new_session_id
from services.prompt_builder import build_onboarding_prompt
from managers.publisher_manager import get_summary_stats
from tools.onboarding_tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _get_system_prompt() -> str:
    """Build system prompt with current CSV context."""
    csv_context = get_summary_stats()
    return build_onboarding_prompt(csv_context)


@router.post("/chat")
async def onboarding_chat(request: Request):
    """Handle onboarding chat messages with tool-use loop."""
    body = await request.json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id", new_session_id())

    if not user_message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    conversation = get_conversation(session_id)
    conversation.append({"role": "user", "content": user_message})

    try:
        client = get_client()
        model = get_model()
        system_prompt = _get_system_prompt()

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
            logger.info(f"Onboarding tool round {tool_round}")

            # Add assistant message with tool_use blocks
            conversation.append({
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            })

            # Execute each tool call
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

            # Feed tool results back
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
        logger.exception("Onboarding chat error")
        # Remove the failed user message
        if conversation and conversation[-1]["role"] == "user":
            conversation.pop()
        return JSONResponse(
            {"error": f"Something went wrong: {str(exc)}"},
            status_code=500,
        )


@router.post("/reset")
async def reset_onboarding(request: Request):
    """Clear onboarding conversation history."""
    body = await request.json()
    session_id = body.get("session_id")
    if session_id:
        clear_conversation(session_id)
    return JSONResponse({"status": "ok"})
