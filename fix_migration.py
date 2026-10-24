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
            
            # List of valid head revisions (migrations that exist and are current heads)
            # Based on current migration files:
            # - 0010_study_buddy_models (head)
            # - f20bbc32f718 (head, depends on 0010_add_quiz_summaries)
            valid_heads = ['0010_study_buddy_models', 'f20bbc32f718']
            
            print(f'\nValid head revisions: {", ".join(valid_heads)}')
            print('\nSetting database to the first valid head: 0010_study_buddy_models')
            print('(You can manually change this later if needed)')
            
            # Set to one of the valid heads
            target = '0010_study_buddy_models'
            
            await conn.execute(text(
                f"UPDATE alembic_version SET version_num = '{target}'"
            ))
            
            print(f'\n✓ Updated database version to: {target}')
            print('\nNext steps:')
            print('1. Run: alembic upgrade heads  (to upgrade all heads)')
            print('2. Then run your new migrations')
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
