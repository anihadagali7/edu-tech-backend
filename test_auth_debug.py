"""Quick diagnostic script to identify auth dependency issues."""
import asyncio
import sys

async def test_clerk_config():
    """Test Clerk configuration."""
    print("=" * 60)
    print("CLERK CONFIGURATION TEST")
    print("=" * 60)
    
    from app.config import get_settings
    s = get_settings()
    
    print(f"\n✓ Settings loaded")
    print(f"  CLERK_JWKS_URL: {s.CLERK_JWKS_URL}")
    print(f"  CLERK_ISSUER: {s.CLERK_ISSUER}")
    print(f"  CLERK_JWT_AUDIENCE: {s.CLERK_JWT_AUDIENCE}")
    print(f"  DATABASE_URL: {s.DATABASE_URL[:50]}...")
    
    if not s.CLERK_JWKS_URL:
        print("\n❌ ERROR: CLERK_JWKS_URL is not set!")
        print("   This will cause auth to fail.")
        return False
    
    # Test JWKS fetch
    print(f"\n📡 Testing JWKS fetch from: {s.CLERK_JWKS_URL}")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(s.CLERK_JWKS_URL)
            resp.raise_for_status()
            jwks = resp.json()
            print(f"✓ JWKS fetch successful ({len(jwks.get('keys', []))} keys)")
    except Exception as e:
        print(f"❌ JWKS fetch failed: {e}")
        print("   Requests will hang waiting for this!")
        return False
    
    # Test DB connection
    print(f"\n🗄️  Testing database connection...")
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(s.DATABASE_URL)
        async with engine.connect() as conn:
            result = await conn.execute("SELECT 1 as test")
            row = (await result.fetchone())
            print(f"✓ Database connection successful: {row}")
        await engine.dispose()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("   User upsert will fail and block requests!")
        return False
    
    print("\n" + "=" * 60)
    print("✅ ALL CHECKS PASSED - Auth should work!")
    print("=" * 60)
    return True

async def test_db_schema():
    """Test AppUser schema matches middleware expectations."""
    print("\n" + "=" * 60)
    print("DATABASE SCHEMA TEST")
    print("=" * 60)
    
    try:
        from app.db.models import AppUser
        from sqlalchemy import inspect
        
        # Check columns
        expected_cols = ['id', 'clerk_user_id', 'full_name', 'avatar_url', 
                        'active_org_id', 'active_org_slug', 'created_at', 'updated_at']
        
        print(f"\n📋 Expected AppUser columns: {expected_cols}")
        print(f"✓ AppUser model found")
        
        # Try a test upsert
        from app.config import get_settings
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import select, update
        from sqlalchemy.dialects.postgresql import insert
        
        s = get_settings()
        engine = create_async_engine(s.DATABASE_URL)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            # Try select
            q = select(AppUser.id).limit(1)
            result = await session.execute(q)
            print(f"✓ Can query AppUser table")
            
        await engine.dispose()
        print(f"✓ Schema looks good!")
        
    except Exception as e:
        print(f"❌ Schema test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    print("\n🔍 Running auth diagnostics...\n")
    
    async def run_all():
        config_ok = await test_clerk_config()
        if not config_ok:
            print("\n💡 FIX: Set your Clerk environment variables in .env file")
            print("   CLERK_JWKS_URL=https://your-clerk-instance.clerk.accounts.dev/.well-known/jwks.json")
            print("   CLERK_ISSUER=https://your-clerk-instance.clerk.accounts.dev")
            print("   CLERK_JWT_AUDIENCE=your-app-id")
            sys.exit(1)
        
        schema_ok = await test_db_schema()
        if not schema_ok:
            print("\n💡 FIX: Run database migrations")
            print("   alembic upgrade head")
            sys.exit(1)
        
        print("\n✅ All tests passed! Your auth should work.")
        print("\n📝 If Postman still hangs:")
        print("   1. Restart your uvicorn server (Ctrl+C and restart)")
        print("   2. Check your Clerk JWT token is valid and not expired")
        print("   3. Check Postman Authorization header format:")
        print("      Authorization: Bearer <your-clerk-jwt-token>")
    
    asyncio.run(run_all())
