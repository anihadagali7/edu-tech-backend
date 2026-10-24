"""
Quick test to verify server is responding
"""
import httpx
import asyncio

async def test_health():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://127.0.0.1:8000/health", timeout=5.0)
            print(f"✅ Server is running!")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
        except httpx.ConnectError:
            print("❌ Server is not running on port 8000")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_health())
