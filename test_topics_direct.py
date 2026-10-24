"""Direct test of the topics endpoint without auth to diagnose the issue."""
import asyncio
from app.db.base import get_session
from app.db.repositories import list_topics

async def test_topics():
    """Test if we can fetch topics from database directly."""
    print("Testing direct database access to topics...")
    
    try:
        async for session in get_session():
            print("✅ Database connection successful")
            
            # Try to list topics
            topics = await list_topics(session, q=None, published_only=True, limit=10, offset=0)
            print(f"✅ Found {len(topics)} topics")
            
            if topics:
                for topic in topics[:3]:
                    print(f"  - {topic.name} (id: {topic.id})")
            else:
                print("  (No topics in database)")
            
            break
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_topics())
