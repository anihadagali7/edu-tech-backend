"""Fix migration version mismatch by updating to the correct revision."""
import asyncio
from app.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def fix_migration():
    """Update alembic_version to match the actual code."""
    engine = create_async_engine(get_settings().DATABASE_URL)
    
    try:
        async with engine.begin() as conn:
            # Check current version
            result = await conn.execute(text('SELECT version_num FROM alembic_version'))
            row = result.fetchone()
            current = row[0] if row else None
            print(f'Current DB version: {current}')
            
            # Update to the version that exists in our code
            # Since 0008_add_organization_support depends on 549eef2d08a5, 
            # let's set it to that parent first
            target = '549eef2d08a5'
            print(f'Updating to: {target}')
            
            await conn.execute(text(
                f"UPDATE alembic_version SET version_num = '{target}'"
            ))
            
            print(f'✓ Updated! Now run: alembic upgrade head')
    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        await engine.dispose()

if __name__ == "__main__":
    print('⚠️  This will update your database migration version.')
    print('    Make sure you have a backup before proceeding!')
    print()
    response = input('Continue? (yes/no): ')
    if response.lower() == 'yes':
        asyncio.run(fix_migration())
    else:
        print('Cancelled.')
