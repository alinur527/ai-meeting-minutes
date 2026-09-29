"""Create local configuration with fresh secrets. Existing files are never overwritten."""
from pathlib import Path
import secrets

target = Path(__file__).resolve().parents[1] / ".env"
with target.open("x", encoding="utf-8") as output:
    output.write("APP_ENV=development\nCOOKIE_SECURE=false\nFRONTEND_ORIGIN=http://localhost:8088\n")
    output.write("POSTGRES_PASSWORD=" + secrets.token_hex(24) + "\n")
    output.write("AI_INTERNAL_TOKEN=" + secrets.token_hex(32) + "\n")
print("Created .env with fresh local secrets")
