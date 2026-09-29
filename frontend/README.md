# Frontend

React / TypeScript / Vite review interface for AI Meeting Minutes. The interface is currently Russian and retains its original AlemProtocol name. Full application setup is in the [deployment guide](../docs/DEPLOYMENT.md).

## Development

Use Node >=22.12. From this directory:

```bash
npm ci
npm run dev -- --host 127.0.0.1
```

Copy `.env.example` to `.env` only if it does not exist. The default setup uses:

```dotenv
VITE_USE_MOCK=false
VITE_API_BASE_URL=/api
BACKEND_URL=http://127.0.0.1:8080
```

Open [localhost:5173](http://localhost:5173). Vite proxies `/api` to the backend, removing that prefix. `BACKEND_URL` must be reachable from the machine running Vite, not necessarily from the browser. The backend port is 8080; the AI service port is 8000. Never put internal AI tokens in frontend settings.

Restart Vite after changing environment settings. `VITE_*` values are embedded during production builds. Upload limits and the processing profile come from authenticated `/capabilities`. Use the exact browser origin in backend `FRONTEND_ORIGIN`.

For a UI-only demo, set `VITE_USE_MOCK=true` and visit `/meetings/demo`. It uses fictional local fixture data and is explicitly labelled. This mode does not prove backend or AI operation. Real processing requires frontend mock mode off, backend HTTP transport with expected real mode, and real AI.

## Review workflow

The interface supports uploads, status polling, meeting history, audio playback, task evidence, transcript search, speaker filtering, task owner / review filtering, speaker mapping, task edits, confirmation / reopening and DOCX export. Source navigation clears filters hiding the target segment. Filters do not limit the exported record.

## Checks

```bash
npm run lint
npm run build
npm run test:browser
```

Build includes TypeScript checking. `test:browser` starts temporary Vite servers and tests UI behavior with controlled API responses, including small viewports, keyboard focus and source navigation. On Windows it uses installed Microsoft Edge; set `BROWSER_PATH` to select another compatible browser. On Linux, install Playwright Chromium with `node node_modules/playwright-core/cli.js install --with-deps chromium`.

`npm run test:connected` expects running API / worker / PostgreSQL plus explicit AI mock. It sends a generated WAV through real HTTP, creates a meeting, reloads audio, saves edits, confirms and downloads DOCX. Configure `TEST_URL`, `TEST_EMAIL` and `TEST_PASSWORD` in the process environment; never put credentials in command arguments or Git. The backend's isolated harness prepares these resources automatically.

`node tests/real.mjs` uses no API substitution. It requires `TEST_URL`, `TEST_REAL_CASE`, `TEST_EMAIL`, `TEST_PASSWORD` and `TEST_ARTIFACT_DIR`. Supply metadata for a recording you are permitted to process. It checks the real mode and browser workflow; content accuracy and the exported document must be evaluated separately. See [verification](../docs/VERIFICATION.md).

## Production build

```bash
npm run build
npm run preview
```

Preview runs on port 4173 and is for local inspection. Root Compose serves `dist` with Nginx and proxies `/api` to the backend. Another server needs an equivalent API proxy and an `index.html` fallback for `/meetings/:id` routes. Vite development / preview servers are not the production deployment.
