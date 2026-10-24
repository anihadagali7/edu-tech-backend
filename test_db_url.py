"""Test database connection and configuration."""
from app.config import get_settings

settings = get_settings()
print(f"DATABASE_URL: {settings.DATABASE_URL}")
print(f"Length: {len(settings.DATABASE_URL)}")
print(f"Has query params: {'?' in settings.DATABASE_URL}")

# Check for any invisible characters or issues
import urllib.parse
parsed = urllib.parse.urlparse(settings.DATABASE_URL)
print(f"\nParsed URL:")
print(f"  Scheme: {parsed.scheme}")
print(f"  Hostname: {parsed.hostname}")
print(f"  Port: {parsed.port}")
print(f"  Path: {parsed.path}")
print(f"  Query: {parsed.query}")
print(f"  Params: {dict(urllib.parse.parse_qsl(parsed.query))}")
