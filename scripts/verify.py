"""Run the complete native A/B gate and bind its evidence to one working tree.

Run with the backend Python; AI_PYTHON, TEST_POSTGRES_ADMIN_URL and PG_BIN
must point to isolated test infrastructure. Never prints environment values.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def snapshot():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8")

    names = sorted(set(git("ls-files", "-co", "--exclude-standard", "-z").strip("\0").split("\0")))
    files = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in names if (ROOT / name).is_file()
    }
    code = {name: digest for name, digest in files.items() if not name.endswith(".md")}
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "head": git("rev-parse", "HEAD").strip(),
        "branch": git("branch", "--show-current").strip(),
        "git_status": git("status", "--short"),
        "files_sha256": files,
        "code_sha256": hashlib.sha256(json.dumps(code, sort_keys=True).encode()).hexdigest(),
        "code_hash_scope": "git tracked and untracked non-ignored files, excluding Markdown; full per-file hashes also retained",
    }


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    artifacts = ROOT / ".artifacts" / ("verify-" + stamp)
    artifacts.mkdir(parents=True)
    env = dict(os.environ, PYTHONUTF8="1", AI_MODE="mock", E2E_ARTIFACT_DIR=str(artifacts / "e2e"))
    missing = [key for key in ("AI_PYTHON", "TEST_POSTGRES_ADMIN_URL", "PG_BIN") if not env.get(key)]
    ai = env.get("AI_PYTHON", "")
    if ai and not Path(ai).is_file():
        missing.append("AI_PYTHON executable")
    for command in ("node", "npm"):
        if not shutil.which(command):
            missing.append(command)
    for command in ("pg_dump", "pg_restore"):
        if env.get("PG_BIN") and not shutil.which(command, path=env["PG_BIN"]):
            missing.append("PG_BIN/" + command)
    if missing:
        report = {"status": "BLOCKED", "missing": missing, "snapshot": snapshot()}
        (artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("BLOCKED: " + ", ".join(missing), flush=True)
        print(artifacts / "report.json", flush=True)
        return 2

    secrets = [env["TEST_POSTGRES_ADMIN_URL"]]
    password = urlsplit(env["TEST_POSTGRES_ADMIN_URL"]).password
    if password:
        secrets.extend([password, unquote(password)])
    secrets.extend(value for key, value in env.items() if value and any(s in key for s in ("TOKEN", "PASSWORD")))

    def redact(value):
        for secret in sorted(set(secrets), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        return value

    before = snapshot()
    results = []

    def run(name, args, cwd, junit=None, requires=None):
        result = {"name": name, "command": args, "cwd": str(cwd), "status": "BLOCKED"}
        if requires and not all(next(r for r in results if r["name"] == dep)["status"] == "PASSED" for dep in requires):
            result["reason"] = "Prerequisite failed: " + ", ".join(requires)
            results.append(result)
            return
        print("RUN: " + name, flush=True)
        started = time.perf_counter()
        path = artifacts / (name + ".log")
        result["log"] = str(path)
        with path.open("w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                for line in process.stdout:
                    log.write(redact(line))
                    log.flush()
                result["exit_code"] = process.wait()
                result["status"] = "PASSED" if result["exit_code"] == 0 else "FAILED"
            except OSError as exc:
                result["reason"] = redact(str(exc))
                result["status"] = "FAILED"
        result["seconds"] = round(time.perf_counter() - started, 3)
        if junit and Path(junit).exists():
            cases = ET.parse(junit).findall(".//testcase")
            skipped = [{"test": c.get("classname", "") + "." + c.get("name", ""), "reason": redact(c.find("skipped").get("message", ""))} for c in cases if c.find("skipped") is not None]
            failures = sum(c.find("failure") is not None or c.find("error") is not None for c in cases)
            result.update(tests=len(cases), passed=len(cases) - len(skipped) - failures, failed=failures, skipped=skipped)
            if skipped and result["status"] == "PASSED":
                result["status"] = "BLOCKED"
        results.append(result)
        print(f'{name}: {result["status"]} ({result["seconds"]}s)', flush=True)

    backend, frontend, ai_dir = ROOT / "backend", ROOT / "frontend", ROOT / "ai-service"
    node, npm = shutil.which("node"), shutil.which("npm")
    backend_xml, ai_xml = str(artifacts / "backend.xml"), str(artifacts / "ai.xml")
    run("backend", [sys.executable, "scripts/run_postgres_tests.py", "-ra", "--junitxml=" + backend_xml], backend, backend_xml)
    run("ai", [ai, "-m", "pytest", "-ra", "--junitxml=" + ai_xml], ai_dir, ai_xml)
    run("ai-lint", [ai, "-m", "ruff", "check", "app", "tests", "scripts"], ai_dir)
    run("python-errors", [ai, "-m", "ruff", "check", "backend", "shared", "scripts", "--select", "F"], ROOT)
    run("backend-dependencies", [sys.executable, "-m", "pip", "check"], backend)
    run("ai-dependencies", [ai, "-m", "pip", "check"], ai_dir)
    run("frontend-lint", [npm, "run", "lint"], frontend)
    run("frontend-typecheck", [node, "node_modules/typescript/bin/tsc", "-b"], frontend)
    run("frontend-build", [npm, "run", "build"], frontend)
    run("browser", [npm, "run", "test:browser"], frontend, requires=["frontend-build"])
    run("http-mock-e2e", [sys.executable, "scripts/run_browser_e2e.py"], backend, requires=["frontend-build"])
    after = snapshot()
    unchanged = before["code_sha256"] == after["code_sha256"] and before["head"] == after["head"]
    status = "PASSED" if unchanged and all(r["status"] == "PASSED" for r in results) else "FAILED"
    report = {"status": status, "scope": "A/B native; explicit HTTP AI mock, not full real AI, containers or CI", "source_unchanged": unchanged, "before": before, "after": after, "checks": results}
    output = artifacts / "report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{status}: {output}", flush=True)
    return 0 if status == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
