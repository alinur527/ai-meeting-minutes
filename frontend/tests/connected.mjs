// Runs against the actual frontend, backend, worker and AI (AI_MODE=mock).
// Creates one test meeting and downloads its protocol; no requests are mocked.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright-core";

const base = process.env.TEST_URL || "http://127.0.0.1:5173";
const executablePath = process.env.BROWSER_PATH || process.env.EDGE_PATH;
const browser = await chromium.launch({
  executablePath,
  channel: !executablePath && process.platform === "win32" ? "msedge" : undefined,
  headless: true,
  args: ["--no-proxy-server", ...(process.env.TEST_HOST_RULES ? [`--host-resolver-rules=${process.env.TEST_HOST_RULES}`] : [])],
});
const errors = [];

function wavFile() {
  const size = 16000 * 2;
  const bytes = Buffer.alloc(44 + size);
  bytes.write("RIFF"); bytes.writeUInt32LE(bytes.length - 8, 4);
  bytes.write("WAVEfmt ", 8); bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(16000, 24); bytes.writeUInt32LE(32000, 28);
  bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34);
  bytes.write("data", 36); bytes.writeUInt32LE(size, 40);
  return bytes;
}

try {
  const page = await browser.newPage({ acceptDownloads: true, timezoneId: "Asia/Almaty" });
  // Emulate the missing API on insecure LAN HTTP origins.
  await page.addInitScript(() => { Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true }); });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base);
  await page.getByLabel("Email", { exact: true }).fill(process.env.TEST_EMAIL);
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByLabel("Название совещания").fill("Проверка полной интеграции");
  await page.getByLabel("Дата и время").fill("2026-09-23T17:00");
  await page.getByLabel("Участник 1").fill("Султан");
  await page.getByRole("button", { name: "Добавить участника" }).click();
  await page.getByLabel("Участник 2").fill("Даурен");

  // Unsupported containers are rejected before any upload is sent.
  let creates = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/meetings") creates++;
  });
  await page.locator('input[type="file"]').setInputFiles({ name: "test.webm", mimeType: "audio/webm", buffer: wavFile() });
  await page.getByRole("button", { name: "Обработать совещание" }).click();
  await page.getByRole("alert").filter({ hasText: "WAV, MP3 или M4A" }).waitFor();
  assert.equal(creates, 0);

  await page.locator('input[type="file"]').setInputFiles({ name: "test.wav", mimeType: "audio/wav", buffer: wavFile() });
  await page.getByRole("button", { name: "Обработать совещание" }).click();
  await page.waitForURL(/\/meetings\/[0-9a-f-]{36}$/);
  const id = new URL(page.url()).pathname.split("/").at(-1);
  if (process.env.TEST_RELOAD_PROCESSING === "true") {
    await page.getByText("Обрабатывается", { exact: true }).waitFor({ timeout: 10000 });
    await page.reload();
  }
  await page.getByText("Готово", { exact: true }).waitFor({ timeout: 30000 });
  assert.equal(creates, 1);
  await page.getByText("Демонстрационный результат: запись не распознавалась").waitFor();
  await page.getByRole("heading", { name: "Краткое содержание" }).waitFor();
  await page.waitForFunction(() => document.querySelector("audio")?.readyState >= 1);

  // Reload must retrieve the persistent recording, not an expired upload blob.
  await page.reload();
  await page.getByText("Готово", { exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector("audio")?.readyState >= 1);
  await page.getByRole("button", { name: "Посмотреть источник" }).first().click();
  assert.equal(await page.locator(".transcript-segment.is-highlighted").count(), 1);

  await page.getByRole("button", { name: "Изменить", exact: true }).first().click();
  await page.getByLabel("Текст поручения").fill("Проверенное поручение из браузера");
  await page.getByLabel("Срок", { exact: true }).fill("2026-09-30");
  await page.getByLabel("Я проверил поручение, ответственного и срок").check();
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await page.getByText("Проверенное поручение из браузера", { exact: true }).waitFor();
  await page.reload();
  await page.getByText("Проверенное поручение из браузера", { exact: true }).waitFor();
  const detail = await page.evaluate(async (meetingId) => (await fetch(`/api/meetings/${meetingId}`)).json(), id);
  assert.equal(detail.action_items[0].due_date, "2026-09-30");
  assert.equal(detail.timezone, "Asia/Almaty");
  assert.match(detail.started_at, /17:00:00\+05:00$/);
  assert.equal(detail.participants.length, 2);
  assert.equal(detail.action_items[0].needs_review, false);
  const range = await page.evaluate(async (meetingId) => {
    const result = await fetch(`/api/meetings/${meetingId}/audio`, { headers: { Range: "bytes=0-15" } });
    return { status: result.status, bytes: (await result.arrayBuffer()).byteLength };
  }, id);
  assert.deepEqual(range, { status: 206, bytes: 16 });

  await page.getByRole("button", { name: "Подтвердить протокол", exact: true }).click();
  await page.getByText("Подтверждён", { exact: true }).waitFor();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать DOCX", exact: true }).click();
  const download = await downloaded;
  const bytes = await readFile(await download.path());
  assert.equal(bytes.subarray(0, 2).toString(), "PK");
  assert.ok(bytes.length > 1000);
  if (process.env.TEST_DOWNLOAD_PATH) await download.saveAs(process.env.TEST_DOWNLOAD_PATH);
  await page.getByRole("button", { name: "Вернуть к редактированию" }).click();
  await page.getByText("Черновик", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Скачать DOCX" }).isDisabled(), true);
  await page.reload();
  await page.getByText("Черновик", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await page.goto(`${base}/meetings/${id}`);
  await page.getByRole("heading", { name: "Вход в AlemProtocol" }).waitFor();
  await page.getByLabel("Email", { exact: true }).fill(process.env.TEST_EMAIL);
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByText("Проверенное поручение из браузера", { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log("Connected PASS: browser -> Vite proxy -> API -> worker -> AI -> DB; audio reload, edits, confirmation, DOCX.");
} finally {
  await browser.close();
}
