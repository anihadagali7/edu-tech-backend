#!/usr/bin/env python3
"""
Example script demonstrating the new topic confirmation workflow.

This shows how the frontend should handle the two-step process:
1. Search for topic - if not found, receive confirmation prompt
2. If user confirms, submit the topic request

Usage:
    python examples/topic_confirmation_flow.py
"""

import asyncio
import httpx
from typing import Dict, Any


# Mock JWT token for testing (replace with real token in production)
MOCK_JWT = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
BASE_URL = "http://localhost:8000"


async def search_topic(query: str) -> Dict[str, Any]:
    """Step 1: Search for a topic."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/topics/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {MOCK_JWT}"}
        )
        return response.json()


async def confirm_topic_request(topic_name: str) -> Dict[str, Any]:
    """Step 2: Submit confirmed topic request."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/topics/request-topic",
            json={"topic_name": topic_name},
            headers={"Authorization": f"Bearer {MOCK_JWT}"}
        )
        return response.json()


async def demonstrate_workflow():
    """Demonstrate the complete confirmation workflow."""
    
    print("=== Topic Confirmation Workflow Demo ===\n")
    
    # Example 1: Search for existing topic (should return matches)
    print("1. Searching for existing topic 'Python Basics'...")
    result = await search_topic("Python Basics")
    print(f"Response: {result}")
    
    if result["data"].get("matches"):
        print("✅ Found existing topic - no confirmation needed\n")
    else:
        print("❌ No matches found\n")
    
    # Example 2: Search for non-existing topic (should trigger confirmation)
    print("2. Searching for new topic 'Advanced Machine Learning'...")
    result = await search_topic("Advanced Machine Learning")
    print(f"Response: {result}")
    
    if result["data"].get("confirmation_required"):
        print("⚠️  Confirmation required!")
        print(f"Message: {result['data']['message']}")
        print(f"Topic slug: {result['data']['topic_slug']}")
        
        # Simulate user confirmation
        print("\n3. User confirms - submitting topic request...")
        confirm_result = await confirm_topic_request("Advanced Machine Learning")
        print(f"Confirmation response: {confirm_result}")
        
        if confirm_result["data"].get("status") == "request_submitted":
            print("✅ Topic request submitted successfully!")
            print(f"Pending ID: {confirm_result['data']['pending_id']}")
        else:
            print("❌ Failed to submit topic request")
    
    print("\n=== Workflow Complete ===")


async def main():
    """Main function to run the demo."""
    try:
        await demonstrate_workflow()
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the FastAPI server is running on localhost:8000")


if __name__ == "__main__":
    asyncio.run(main())