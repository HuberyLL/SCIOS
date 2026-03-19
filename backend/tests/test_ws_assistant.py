"""Quick WebSocket smoke-test for the assistant chat loop.

Run with:  uv run python tests/test_ws_assistant.py
"""

import asyncio
import json

import httpx
import websockets


API = "http://localhost:8000/api/v1/assistant"
WS_BASE = "ws://localhost:8000/api/v1/assistant/ws"


async def main() -> None:
    # 1. Create a session via REST
    async with httpx.AsyncClient() as http:
        resp = await http.post(f"{API}/sessions", json={"title": "WS Test"})
        resp.raise_for_status()
        session_id = resp.json()["id"]
        print(f"[+] Created session: {session_id}")

    # 2. Connect via WebSocket
    ws_url = f"{WS_BASE}/{session_id}"
    print(f"[+] Connecting to {ws_url} ...")
    async with websockets.connect(ws_url) as ws:
        # 3. Send a message that should trigger the get_system_time tool
        payload = {"content": "Now what time is it? Please use the get_system_time tool to check it."}
        await ws.send(json.dumps(payload))
        print(f"[>] Sent: {payload['content']}")

        # 4. Collect all events until message_complete or error
        events: list[dict] = []
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            event = json.loads(raw)
            events.append(event)
            etype = event.get("event", "")
            print(f"  [{etype}] {json.dumps(event.get('data', {}), ensure_ascii=False)}")
            if etype in ("message_complete", "error"):
                break

    # 5. Verify the event sequence
    event_types = [e["event"] for e in events]
    print(f"\n[=] Event sequence: {event_types}")

    assert "tool_call_start" in event_types, "Expected a tool_call_start event"
    assert "tool_call_result" in event_types, "Expected a tool_call_result event"
    assert "message_complete" in event_types, "Expected a message_complete event"

    # 6. Verify DB persistence via REST
    async with httpx.AsyncClient() as http:
        resp = await http.get(f"{API}/sessions/{session_id}")
        resp.raise_for_status()
        messages = resp.json()["messages"]
        roles = [m["role"] for m in messages]
        print(f"[=] DB message roles: {roles}")
        assert "user" in roles
        assert "assistant" in roles
        assert "tool" in roles

    print("\n[OK] All checks passed!")


if __name__ == "__main__":
    asyncio.run(main())
