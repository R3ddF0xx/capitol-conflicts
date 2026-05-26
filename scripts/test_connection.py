import requests
from dotenv import load_dotenv
import os

load_dotenv()

url = os.environ.get("SUPABASE_URL", "NOT FOUND")
key = os.environ.get("SUPABASE_SERVICE_KEY", "NOT FOUND")

print(f"URL: {url}")
print(f"Service key set: {'YES' if key != 'NOT FOUND' and len(key) > 10 else 'NO - missing from .env'}")

try:
    r = requests.get(url, timeout=10)
    print(f"Connection OK: {r.status_code}")
except Exception as e:
    print(f"Connection FAILED: {e}")
