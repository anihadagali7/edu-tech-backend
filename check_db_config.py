"""Check DATABASE_URL configuration."""
from app.config import get_settings

s = get_settings()
db_url = s.DATABASE_URL

print("DATABASE_URL configuration:")
print("-" * 60)

if "5432" in db_url:
    print("✓ Using port 5432 (Direct connection)")
    print("  Good for long-lived connections")
elif "6543" in db_url:
    print("⚠️  Using port 6543 (Connection pooler)")
    print("  This can cause 'connection closed' errors with async")
    print()
    print("💡 FIX: Change your DATABASE_URL to use port 5432")
    print("   Or add ?prepared_statement_cache_size=0 to the URL")
else:
    print("❓ Unknown port configuration")

print()
print(f"Current URL (masked): {db_url[:50]}...")

# Check for connection pooling parameters
if "prepared_statement_cache_size" in db_url:
    print("✓ Has prepared_statement_cache_size parameter")
else:
    print("⚠️  Missing prepared_statement_cache_size parameter")
    print("   Add ?prepared_statement_cache_size=0 to fix pooler issues")
