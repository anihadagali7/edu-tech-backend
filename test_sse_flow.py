"""Test the /topics endpoint and then /sse/quiz/start with the actual ID."""
import asyncio
import httpx
import json

async def test_flow():
    base_url = "http://127.0.0.1:8000"
    
    # Note: This test will fail auth but we can see the 401 response structure
    print("Testing /topics endpoint...")
    async with httpx.AsyncClient() as client:
        try:
            # Try without auth to see structure
            resp = await client.get(f"{base_url}/topics")
            print(f"Status: {resp.status_code}")
            if resp.status_code == 401:
                print("✅ Expected auth error (need Clerk token)")
            else:
                try:
                    data = resp.json()
                    print(f"Response: {json.dumps(data, indent=2)[:500]}")
                    
                    if data.get("data", {}).get("items"):
                        first_topic = data["data"]["items"][0]
                        topic_id = first_topic["id"]
                        print(f"\n✅ First topic ID: {topic_id}")
                        print(f"   Type: {type(topic_id).__name__}")
                        print(f"   Length: {len(topic_id)}")
                        print(f"   Has dashes: {'-' in topic_id}")
                        
                        # Try to use it in SSE endpoint
                        print(f"\n📡 Testing SSE endpoint with topic_id={topic_id}")
                        sse_url = f"{base_url}/sse/quiz/start?topic_id={topic_id}"
                        print(f"   URL: {sse_url}")
                        
                except Exception as e:
                    print(f"❌ Error parsing response: {e}")
        except Exception as e:
            print(f"❌ Request error: {e}")

if __name__ == "__main__":
    asyncio.run(test_flow())
