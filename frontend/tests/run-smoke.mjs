import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir } from "node:fs/promises";

const children = [];
function start(args, env) {
  const child = spawn(process.execPath, args, { env: { ...process.env, ...env }, stdio: "inherit", windowsHide: true });
  children.push(child);
  return child;
}
try {
  for (const [port, mock] of [[5187, "true"], [5188, "false"]]) {
    const child = start(["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(port)], { VITE_USE_MOCK: mock });
    let ready = false;
    for (let i = 0; i < 100; i++) {
      if (child.exitCode !== null) throw new Error("Vite exited before readiness");
      try { ready = (await fetch(`http://127.0.0.1:${port}`)).ok; } catch {}
      if (ready) break;
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    if (!ready) throw new Error("Vite readiness timeout");
  }
  await mkdir("../.artifacts/screenshots", { recursive: true });
  const test = start(["tests/smoke.mjs"], {
    TEST_URL: "http://127.0.0.1:5187", REAL_TEST_URL: "http://127.0.0.1:5188",
    TEST_SCREENSHOT_DIR: "../.artifacts/screenshots",
  });
  const [code] = await once(test, "exit");
  if (code !== 0) process.exitCode = code || 1;
} finally {
  for (const child of children) if (child.exitCode === null) child.kill();
}
