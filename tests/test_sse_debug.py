"""Test SSE streaming with actual LLM (requires API key)"""
import asyncio
import os
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.study_buddy import service as study_service


@pytest.mark.asyncio
async def test_sse_with_real_llm(
    monkeypatch: pytest.MonkeyPatch,
    client_fixture: AsyncClient,
    db_session: AsyncSession
) -> None:
    """Test SSE streaming with real LLM to see actual responses."""
    
    # Enable features
    from app.features.study_buddy import router as study_router
    monkeypatch.setattr(study_router, "ENABLE_STUDY_BUDDY", True)
    monkeypatch.setenv("STUDY_BUDDY_USE_OPENAI", "1")
    monkeypatch.setenv("STUDY_BUDDY_MODEL", "gpt-4")
    
    # Check if API key is available
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")
    
    # Create session
    session_response = await client_fixture.post(
        "/study-buddy/sessions",
        json={"mode": "quiz"}
    )
    assert session_response.status_code == 201
    session_id = session_response.json()["session_id"]
    print(f"Created session: {session_id}")
    
    # Post a message
    message_response = await client_fixture.post(
        f"/study-buddy/sessions/{session_id}/messages",
        json={"message": "I'm confused about fractions. Can you help me understand 1/2 + 1/4?"}
    )
    assert message_response.status_code == 202
    print(f"Posted message, response: {message_response.json()}")
    
    # Connect to SSE stream
    print("Connecting to SSE stream...")
    async with client_fixture.stream(
        "GET",
        f"/study-buddy/sessions/{session_id}/stream",
        timeout=30.0
    ) as response:
        print(f"Stream response status: {response.status_code}")
        print(f"Stream response headers: {dict(response.headers)}")
        
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        
        # Read events
        events_received = []
        line_count = 0
        async for line in response.aiter_lines():
            line_count += 1
            print(f"[{line_count}] Received line: {repr(line)}")
            
            if line.startswith("data:"):
                try:
                    import json
                    event_data = json.loads(line[5:].strip())
                    events_received.append(event_data)
                    print(f"  -> Parsed event: {event_data}")
                except json.JSONDecodeError as e:
                    print(f"  -> JSON decode error: {e}")
                    print(f"  -> Raw data: {line[5:].strip()}")
            elif line.startswith("event:"):
                print(f"  -> Event type: {line[6:].strip()}")
            elif line.strip():
                print(f"  -> Other line: {line}")
            
            # Stop after receiving some events or too many lines
            if len(events_received) >= 5 or line_count >= 50:
                print(f"Stopping after {len(events_received)} events or {line_count} lines")
                break
        
        print(f"\nTotal events received: {len(events_received)}")
        print(f"Total lines received: {line_count}")
        
        if events_received:
            print("\nFirst event:")
            print(events_received[0])
        
        assert len(events_received) > 0, f"No events received after {line_count} lines"


if __name__ == "__main__":
    # Run with: python -m pytest test_sse_debug.py -xvs
    pass
