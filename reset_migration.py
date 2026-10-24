"""Reset Alembic migration version to a specific revision.

This script allows you to reset the migration version in the database
to match what actually exists in your migration files.
"""
import asyncio
from app.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def reset_migration(target_version: str | None = None):
    """Reset migration version to a specific revision or to base."""
    engine = create_async_engine(get_settings().DATABASE_URL)
    
    try:
        async with engine.begin() as conn:
            # Check current version
            result = await conn.execute(text('SELECT version_num FROM alembic_version'))
            row = result.fetchone()
            current = row[0] if row else None
            print(f'Current DB version: {current}')
            
            if target_version is None:
                # List available head revisions
                valid_heads = ['0010_study_buddy_models', 'f20bbc32f718', '0010_add_quiz_summaries']
                print(f'\nAvailable head revisions to set:')
                for i, head in enumerate(valid_heads, 1):
                    print(f'  {i}. {head}')
                
                # Default to first head
                target = valid_heads[0]
                print(f'\nSetting to: {target} (first head)')
            else:
                target = target_version
                print(f'\nSetting to: {target}')
            
            await conn.execute(text(
                f"UPDATE alembic_version SET version_num = '{target}'"
            ))
            
            print(f'\n✓ Updated database version to: {target}')
            print('\nNext: Run "alembic upgrade heads" to upgrade all heads')
            
    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        await engine.dispose()

if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else None
    print('⚠️  This will update your database migration version.')
    print('    Make sure you have a backup before proceeding!')
    print()
    response = input('Continue? (yes/no): ')
    if response.lower() == 'yes':
        asyncio.run(reset_migration(target))
    else:
        print('Cancelled.')

