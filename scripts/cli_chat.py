#!/usr/bin/env python3
"""Notex CLI Chat - Interactive chat via the Notex API.

Usage:
    # Start interactive chat (new conversation)
    python scripts/cli_chat.py

    # Start with an initial message
    python scripts/cli_chat.py -m "Istanbul'da hava kac derece?"

    # Continue existing conversation
    python scripts/cli_chat.py -c <conversation_id>

    # Custom API URL
    python scripts/cli_chat.py --url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import httpx

# Fixed UUID for CLI user - always reuses the same guest account
CLI_CLIENT_UUID = "00000000-0000-4000-a000-c11000000001"

DEFAULT_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 60


# ── HTTP helpers ─────────────────────────────────────────────────────


async def register_guest(client: httpx.AsyncClient, base: str) -> dict[str, Any]:
    r = await client.post(
        f"{base}/register/guest",
        json={"client_uuid": CLI_CLIENT_UUID, "timezone": "Europe/Istanbul"},
    )
    r.raise_for_status()
    return r.json()


async def create_conversation(
    client: httpx.AsyncClient, base: str, headers: dict[str, str]
) -> str:
    r = await client.post(f"{base}/v1/conversations", headers=headers)
    r.raise_for_status()
    return r.json()["id"]


async def send_message(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    conversation_id: str,
    content: str,
) -> dict[str, Any]:
    r = await client.post(
        f"{base}/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={
            "content": content,
            "timezone": "Europe/Istanbul",
            "auto_apply": True,
        },
    )
    r.raise_for_status()
    return r.json()


async def fetch_proposal_reasoning(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    proposal_id: str,
) -> str | None:
    """Fetch proposal and extract reasoning (fallback for no-text events)."""
    try:
        r = await client.get(
            f"{base}/v1/proposals/{proposal_id}", headers=headers
        )
        r.raise_for_status()
        ops = r.json().get("ops") or {}
        return ops.get("reasoning")
    except Exception:
        return None


# ── Response extraction ──────────────────────────────────────────────


def extract_text(data: dict[str, Any]) -> str | None:
    """Extract display text from a WebSocket event's data payload."""
    # 1. Top-level tool_response (weather, FX, etc.)
    tr = data.get("tool_response") or {}
    if tr.get("text"):
        return tr["text"]

    # 2. tool_response inside message_ops
    mops = data.get("message_ops") or {}
    mtr = mops.get("tool_response") or {}
    if mtr.get("text"):
        return mtr["text"]

    # 3. Reasoning (ops-mode with auto_apply=false)
    if data.get("reasoning"):
        return data["reasoning"]

    # 4. Operations summary
    ops_list = mops.get("ops") or []
    if ops_list:
        lines = []
        for op in ops_list:
            op_type = op.get("type", "?")
            title = op.get("title", "")
            lines.append(f"  [{op_type}] {title}" if title else f"  [{op_type}]")
        return "Operations:\n" + "\n".join(lines)

    return None


# ── WebSocket event pump ─────────────────────────────────────────────


async def ws_event_pump(
    ws_url: str,
    queue: asyncio.Queue[dict[str, Any]],
    connected: asyncio.Event,
) -> None:
    """Connect to WebSocket and push all events into a queue."""
    try:
        import websockets  # type: ignore[import-untyped]
    except ImportError:
        print(
            "Error: 'websockets' package required. "
            "Install: pip install websockets",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        async with websockets.connect(ws_url) as ws:
            connected.set()
            async for raw in ws:
                try:
                    event = json.loads(raw)
                    await queue.put(event)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        # Push a sentinel so the main loop unblocks
        await queue.put({"type": "_ws_error", "error": str(e)})


# ── Main ─────────────────────────────────────────────────────────────


async def send_and_wait(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    conv_id: str,
    queue: asyncio.Queue[dict[str, Any]],
    message: str,
    timeout: int,
) -> str:
    """Send a message and wait for the response via WebSocket events."""
    try:
        enqueued = await send_message(client, base, headers, conv_id, message)
    except httpx.HTTPStatusError as e:
        return f"Send failed: {e.response.status_code} {e.response.text}"

    msg_id = str(enqueued["message_id"])

    response_text: str | None = None

    try:
        async with asyncio.timeout(timeout):
            while True:
                event = await queue.get()

                if event.get("type") == "_ws_error":
                    return f"WebSocket error: {event.get('error')}"

                if str(event.get("message_id")) != msg_id:
                    continue

                evt_type = event.get("type", "")
                data = event.get("data") or {}
                proposal_id = str(event.get("proposal_id", ""))

                if evt_type in ("proposal.ready", "proposal.applied"):
                    response_text = extract_text(data)

                    if not response_text and proposal_id:
                        response_text = await fetch_proposal_reasoning(
                            client, base, headers, proposal_id
                        )

                    if not response_text:
                        items = data.get("items_affected", 0)
                        if items:
                            response_text = f"Applied ({items} items affected)"
                        else:
                            response_text = "(Processed)"
                    break

                elif evt_type == "proposal.needs_confirmation":
                    mops = data.get("message_ops") or {}
                    ops = mops.get("ops") or []
                    titles = [
                        op.get("title", op.get("type", "?")) for op in ops
                    ]
                    response_text = "Needs confirmation: " + ", ".join(titles)
                    break

                elif evt_type == "proposal.failed":
                    response_text = f"Error: {data.get('error', 'Unknown')}"
                    break

    except asyncio.TimeoutError:
        response_text = f"Timeout: no response within {timeout}s"

    return response_text or "(No response)"


async def run(args: argparse.Namespace) -> None:
    base = args.url.rstrip("/")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(args.timeout + 10, connect=10),
    ) as client:

        # ── 1. Auth ──────────────────────────────────────────────────
        try:
            auth = await register_guest(client, base)
        except httpx.HTTPStatusError as e:
            print(f"Auth failed: {e.response.status_code}", file=sys.stderr)
            sys.exit(1)

        token = auth["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # ── 2. Conversation ──────────────────────────────────────────
        if args.conversation:
            conv_id = args.conversation
        else:
            try:
                conv_id = await create_conversation(client, base, headers)
            except httpx.HTTPStatusError as e:
                print(
                    f"Create conversation failed: {e.response.status_code}",
                    file=sys.stderr,
                )
                sys.exit(1)

        # ── 3. Start WebSocket ───────────────────────────────────────
        ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/v1/ws/conversations/{conv_id}"

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        ws_connected = asyncio.Event()

        ws_task = asyncio.create_task(ws_event_pump(ws_url, queue, ws_connected))

        try:
            async with asyncio.timeout(5):
                await ws_connected.wait()
        except asyncio.TimeoutError:
            print("WebSocket connection timeout", file=sys.stderr)
            ws_task.cancel()
            sys.exit(1)

        print(f"conversation: {conv_id}")
        print("Type your messages below. Press Ctrl+C or type 'exit' to quit.\n")

        # ── 4. Send first message (from -m flag) ─────────────────────
        if args.message:
            print(f"you> {args.message}")
            response = await send_and_wait(
                client, base, headers, conv_id, queue, args.message, args.timeout
            )
            print(f"bot> {response}\n")

        # ── 5. Interactive loop ──────────────────────────────────────
        try:
            while True:
                try:
                    user_input = await asyncio.to_thread(input, "you> ")
                except EOFError:
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
                    break

                response = await send_and_wait(
                    client, base, headers, conv_id, queue, user_input, args.timeout
                )
                print(f"bot> {response}\n")

        except KeyboardInterrupt:
            print()

        # ── 6. Cleanup ───────────────────────────────────────────────
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass

        print(f"\n--- conversation: {conv_id} ---")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Notex CLI - Send messages and receive responses",
    )
    parser.add_argument("-m", "--message", help="Initial message to send (then enters interactive mode)")
    parser.add_argument(
        "-c",
        "--conversation",
        help="Conversation ID to continue (omit for new)",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"API base URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Response timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
