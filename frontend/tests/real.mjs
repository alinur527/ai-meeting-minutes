// Opt-in local recording test against an already running real deployment.
// No API interception. Reference answers are deliberately not accepted here.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const required = ["TEST_REAL_CASE", "TEST_URL", "TEST_EMAIL", "TEST_PASSWORD", "TEST_ARTIFACT_DIR"];
for (const key of required) assert.ok(process.env[key], `BLOCKED: ${key} required`);
const testCase = JSON.parse(await readFile(process.env.TEST_REAL_CASE, "utf8"));
const allowed = new Set(["audio", "title", "started_at", "timezone", "participants", "consent", "category"]);
assert.ok(Object.keys(testCase).every((key) => allowed.has(key)), "Case accepts metadata only; keep reference answers separate");
assert.equal(testCase.consent, true, "Local processing consent is required");
assert.ok(["human", "synthetic", "unknown"].includes(testCase.category));
assert.ok(Array.isArray(testCase.participants) && testCase.participants.length > 0);
assert.ok(path.isAbsolute(testCase.audio));
assert.ok(testCase.timezone && testCase.started_at && testCase.title);
const artifacts = path.resolve(process.env.TEST_ARTIFACT_DIR);
await mkdir(artifacts, { recursive: true });
const audioHash = createHash("sha256").update(await readFile(testCase.audio)).digest("hex");
const executablePath = process.env.BROWSER_PATH || process.env.EDGE_PATH;
const browser = await chromium.launch({
  executablePath,
  channel: !executablePath && process.platform === "win32" ? "msedge" : undefined,
  headless: true,
  args: ["--no-proxy-server"],
});
const report = { status: "FAILED", category: testCase.category, audio_sha256: audioHash, quality: "NOT_MEASURED", mode: "real" };
try {
  const page = await browser.newPage({ acceptDownloads: true, timezoneId: testCase.timezone });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.name));
  await page.goto(process.env.TEST_URL);
  await page.getByLabel("Email", { exact: true }).fill(process.env.TEST_EMAIL);
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByLabel("Название совещания").waitFor();
  const capabilities = await page.evaluate(async () => (await fetch("/api/capabilities")).json());
  assert.equal(capabilities.processing_profile, "real", "Refusing upload to a mock profile");
  const started = performance.now();
  let id = process.env.TEST_REAL_MEETING;
  if (id) {
    await page.goto(new URL(`/meetings/${id}`, process.env.TEST_URL).href);
  } else {
    await page.getByLabel("Название совещания").fill(testCase.title);
    await page.getByLabel("Дата и время").fill(testCase.started_at);
    for (let index = 0; index < testCase.participants.length; index++) {
      if (index > 0) await page.getByRole("button", { name: "Добавить участника" }).click();
      await page.getByLabel(`Участник ${index + 1}`, { exact: true }).fill(testCase.participants[index]);
    }
    await page.locator('input[type="file"]').setInputFiles(testCase.audio);
    await page.getByRole("button", { name: "Обработать совещание" }).click();
    await page.waitForURL(/\/meetings\/[0-9a-f-]{36}$/);
    id = new URL(page.url()).pathname.split("/").at(-1);
  }
  report.meeting_id = id;
  await page.reload();
  const deadline = performance.now() + Number(process.env.TEST_REAL_TIMEOUT_MS || 1800000);
  report.states = [];
  while (performance.now() < deadline) {
    const state = await page.evaluate(async (meetingId) => {
      const response = await fetch(`/api/meetings/${meetingId}`);
      if (!response.ok) throw new Error(`Meeting polling HTTP ${response.status}`);
      return (await response.json()).status;
    }, id);
    if (report.states.at(-1) !== state) report.states.push(state);
    if (["completed", "failed"].includes(state)) break;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  const before = await page.evaluate(async (meetingId) => (await fetch(`/api/meetings/${meetingId}`)).json(), id);
  report.processing_seconds = Math.round((performance.now() - started) / 100) / 10;
  await writeFile(path.join(artifacts, "result-before.json"), JSON.stringify(before, null, 2));
  assert.equal(before.status, "completed", "Pipeline failed; inspect local result-before.json");
  assert.equal(before.processing_mode, "real");
  assert.ok(before.segments.length > 0 && before.duration_ms > 0);
  assert.equal(before.timezone, testCase.timezone);
  await page.getByText("Готово", { exact: true }).waitFor();
  assert.equal(await page.getByText("Демонстрационный результат: запись не распознавалась").count(), 0);
  await page.waitForFunction(() => document.querySelector("audio")?.readyState >= 1);
  const range = await page.evaluate(async (meetingId) => {
    const response = await fetch(`/api/meetings/${meetingId}/audio`, { headers: { Range: "bytes=0-15" } });
    return { status: response.status, bytes: (await response.arrayBuffer()).byteLength };
  }, id);
  assert.deepEqual(range, { status: 206, bytes: 16 });
  const speaker = before.speakers[0];
  assert.ok(speaker, "No real speaker mapping");
  const speakerSelect = page.locator(".speaker-mappings select").first();
  await speakerSelect.selectOption(before.participants[0].id);
  await speakerSelect.waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.querySelector(".speaker-mappings select")?.disabled);
  await page.reload();
  await page.getByText("Готово", { exact: true }).waitFor();
  assert.equal(await speakerSelect.inputValue(), before.participants[0].id);
  assert.ok(before.action_items.length > 0, "No extracted tasks; edit scenario and quality require investigation");
  const query = before.segments[0].text.split(/\s+/).find((word) => word.length > 3);
  assert.ok(query);
  await page.getByLabel("Поиск по транскрипту").fill(query.toLocaleUpperCase());
  assert.equal(await page.locator(".transcript-segment").count(), before.segments.filter((segment) => segment.text.toLocaleLowerCase().includes(query.toLocaleLowerCase())).length);
  assert.ok(await page.locator(".transcript-segment mark").count() > 0);
  await page.getByLabel("Поиск по транскрипту").fill("");
  await page.getByLabel("Фильтр транскрипта: говорящий", { exact: true }).selectOption(speaker.label);
  assert.equal(await page.locator(".transcript-segment").count(), before.segments.filter((segment) => segment.speaker === speaker.label).length);
  await page.getByLabel("Поиск по транскрипту").fill("несуществующая-фраза-проверки");
  await page.getByRole("button", { name: "Посмотреть источник" }).first().click();
  await page.locator(".transcript-segment.is-highlighted").waitFor();
  assert.equal(await page.getByLabel("Поиск по транскрипту").inputValue(), "");
  assert.equal(await page.getByLabel("Фильтр транскрипта: говорящий", { exact: true }).inputValue(), "");
  await page.getByLabel("Фильтр поручений: исполнитель", { exact: true }).selectOption("__unassigned");
  assert.equal(await page.locator("tbody tr").count(), before.action_items.filter((item) => !item.assignee_id).length);
  await page.getByLabel("Фильтр поручений: исполнитель", { exact: true }).selectOption("");
  await page.getByLabel("Фильтр поручений: проверка", { exact: true }).selectOption("needs_review");
  assert.equal(await page.locator("tbody tr").count(), before.action_items.filter((item) => item.needs_review).length);
  await page.getByRole("button", { name: "Сбросить фильтры поручений" }).click();
  report.filters = "PASSED";
  const edited = before.action_items[0].text + " [проверка сохранения правки]";
  await page.getByRole("button", { name: "Изменить", exact: true }).first().click();
  await page.getByLabel("Текст поручения").fill(edited);
  await page.getByRole("combobox", { name: /^Ответственный/ }).selectOption("");
  await page.getByLabel("Срок", { exact: true }).fill("");
  await page.getByLabel("Я проверил поручение, ответственного и срок").check();
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await page.getByText(edited, { exact: true }).waitFor();
  await page.reload();
  await page.getByText(edited, { exact: true }).waitFor();
  await page.getByRole("button", { name: "Подтвердить протокол", exact: true }).click();
  await page.getByText("Подтверждён", { exact: true }).waitFor();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать DOCX", exact: true }).click();
  const download = await downloadEvent;
  await download.saveAs(path.join(artifacts, "protocol.docx"));
  const after = await page.evaluate(async (meetingId) => (await fetch(`/api/meetings/${meetingId}`)).json(), id);
  await writeFile(path.join(artifacts, "result-after.json"), JSON.stringify(after, null, 2));
  await page.locator(".transcript-segment").first().scrollIntoViewIfNeeded();
  assert.ok(await page.locator(".transcript-segment p").first().isVisible());
  await page.screenshot({ path: path.join(artifacts, "real-meeting.png"), fullPage: true, style: ".transcript-segment { content-visibility: visible !important; }" });
  const saved = after.action_items.find((item) => item.id === before.action_items[0].id);
  assert.equal(saved.text, edited);
  assert.equal(saved.assignee_id, null);
  assert.equal(saved.due_date, null);
  assert.ok(after.confirmed_at);
  assert.deepEqual(errors, []);
  report.status = "PASSED";
  report.duration_ms = before.duration_ms;
  report.segments = before.segments.length;
  report.tasks = before.action_items.length;
  report.speakers = before.speakers.length;
  console.log("PASSED: real UI pipeline, search/speaker/task filters, saved speaker and task edits, null fields, confirmation and download. Content quality and DOCX contents need separate verification.");
} finally {
  await writeFile(path.join(artifacts, "ui-report.json"), JSON.stringify(report, null, 2));
  await browser.close();
}
