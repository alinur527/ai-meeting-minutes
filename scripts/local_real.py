"""Start the prepared local CPU stack without saving or printing credentials.

Uses the standalone model cache and Ollama volume. Existing database credentials
are recovered from Docker in memory so restarting never changes the DB password.
"""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI_CONTAINER = "ai-service-ai-service-1"
DB_CONTAINER = "exit1-real-db-1"


def container_environment(name):
    result = subprocess.run(
        ["docker", "inspect", name], capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode:
        return {}
    return dict(
        entry.split("=", 1)
        for entry in json.loads(result.stdout)[0]["Config"]["Env"]
        if "=" in entry
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "status", "check"])
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True)
    ai = container_environment(AI_CONTAINER)
    db = container_environment(DB_CONTAINER)
    if args.command == "start" and not db and not os.environ.get("POSTGRES_PASSWORD"):
        volume = subprocess.run(
            ["docker", "volume", "inspect", "exit1-real_database"], capture_output=True
        )
        if volume.returncode == 0:
            raise SystemExit(
                "Existing database volume has no matching container. Supply its original "
                "POSTGRES_PASSWORD in this process environment; do not remove the volume."
            )
    env = dict(
        os.environ,
        INTERNAL_TOKEN=os.environ.get("INTERNAL_TOKEN")
        or ai.get("INTERNAL_TOKEN")
        or secrets.token_hex(32),
        POSTGRES_PASSWORD=db.get("POSTGRES_PASSWORD")
        or os.environ.get("POSTGRES_PASSWORD")
        or secrets.token_hex(24),
        AI_MODE="real",
        OLLAMA_PORT=os.environ.get("OLLAMA_PORT", "11435"),
        FRONTEND_ORIGIN="http://localhost:8088",
        WEB_PORT="8088",
    )
    env["AI_INTERNAL_TOKEN"] = env["INTERNAL_TOKEN"]
    local_config = ROOT / "ai-service/.env"
    if args.command == "start" and not local_config.exists():
        config = (ROOT / "ai-service/.env.example").read_text(encoding="utf-8")
        config = config.replace("LOW_MEMORY_MODE=0", "LOW_MEMORY_MODE=1")
        local_config.write_text(config, encoding="utf-8")

    ai_compose = [
        "docker",
        "compose",
        "-p",
        "ai-service",
        "-f",
        "ai-service/docker-compose.yml",
    ]
    app_compose = [
        "docker",
        "compose",
        "-p",
        "exit1-real",
        "-f",
        "compose.yml",
        "-f",
        "compose.local-real.yml",
    ]

    def run(command):
        subprocess.run(command, cwd=ROOT, env=env, check=True)

    if args.command == "check":
        for prefix in (ai_compose, app_compose):
            run(prefix + ["config", "--quiet"])
    elif args.command == "status":
        for prefix in (ai_compose, app_compose):
            run(prefix + ["ps"])
    else:
        options = ["--build"] if args.build else ["--no-build"]
        run(ai_compose + ["up", "-d", *options, "ollama", "ai-service"])
        run(app_compose + ["up", "-d", *options, "db", "api", "worker", "web"])
        print("Local real stack: http://localhost:8088")


if __name__ == "__main__":
    main()
