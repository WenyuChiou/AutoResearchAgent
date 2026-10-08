"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const playwrightModule = process.env.PLAYWRIGHT_MODULE;
assert(playwrightModule, "PLAYWRIGHT_MODULE must name the installed Playwright module");
const { chromium } = require(playwrightModule);
assert(process.argv[2], "pass a generated index.html path");
const viewPath = path.resolve(process.argv[2]);
assert(fs.existsSync(viewPath), "pass an existing generated index.html path");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    acceptDownloads: true,
  });
  const page = await context.newPage();
  const errors = [];
  const externalRequests = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (/^(file:|data:|blob:)/.test(url)) return route.continue();
    externalRequests.push(url);
    return route.abort();
  });

  const checks = [];
  const check = (name, condition) => {
    assert(condition, name);
    checks.push(name);
  };

  try {
    await page.goto(pathToFileURL(viewPath).href, { waitUntil: "load" });
    const frame = page.locator(".graph-frame");
    const svg = page.locator("svg.literature-graph");
    const scene = page.locator(".graph-scene");
    const papers = page.locator(".graph-node.paper");
    const paperCount = await papers.count();
    check("graph renders multiple version-bound papers", paperCount > 3);

    const clicked = papers.nth(1);
    const clickedId = await clicked.getAttribute("data-paper-id");
    await clicked.click();
    check(
      "mouse click selects exact version identity",
      (await page.locator(".graph-node.paper.selected").getAttribute("data-paper-id")) ===
        clickedId,
    );
    const keyboard = papers.nth(3);
    const keyboardId = await keyboard.getAttribute("data-paper-id");
    await keyboard.focus();
    const keyboardBefore = await keyboard.getAttribute("transform");
    await keyboard.press("ArrowRight");
    check("keyboard moves a node", (await keyboard.getAttribute("transform")) !== keyboardBefore);
    await keyboard.press("Enter");
    check(
      "keyboard selects exact version identity",
      (await page.locator(".graph-node.paper.selected").getAttribute("data-paper-id")) ===
        keyboardId,
    );
    const dragged = papers.nth(2);
    const dragBaseline = await dragged.getAttribute("transform");
    const dragBox = await dragged.locator("circle").first().boundingBox();
    await page.mouse.move(dragBox.x + dragBox.width / 2, dragBox.y + dragBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(dragBox.x + dragBox.width / 2 + 42, dragBox.y + dragBox.height / 2 + 28, {
      steps: 5,
    });
    await page.mouse.up();
    check("pointer drag moves a node", (await dragged.getAttribute("transform")) !== dragBaseline);
    check(
      "drag does not select the dragged node",
      (await page.locator(".graph-node.paper.selected").getAttribute("data-paper-id")) ===
        keyboardId,
    );
    await page.getByRole("button", { name: "Reset layout", exact: true }).click();
    check("reset restores deterministic layout", (await papers.nth(2).getAttribute("transform")) === dragBaseline);
    await page.getByRole("button", { name: "Zoom +", exact: true }).click();
    check("zoom button changes scale", Number(await svg.getAttribute("data-zoom")) > 1);
    await page.getByRole("button", { name: "Fit", exact: true }).click();
    check("fit restores scale", (await svg.getAttribute("data-zoom")) === "1.00");

    const svgBox = await svg.boundingBox();
    const sceneBefore = await scene.getAttribute("transform");
    await page.mouse.move(svgBox.x + 8, svgBox.y + 8);
    await page.mouse.down();
    await page.mouse.move(svgBox.x + 48, svgBox.y + 36, { steps: 4 });
    await page.mouse.up();
    check("canvas drag pans", (await scene.getAttribute("transform")) !== sceneBefore);
    await page.getByRole("button", { name: "Fit", exact: true }).click();
    await page.locator('[data-literature-filter="text"]').fill(keyboardId);
    check("identity filter keeps one version", (await papers.count()) === 1);
    await page.locator('[data-literature-filter="text"]').fill("");
    check("filter reset restores all versions", (await papers.count()) === paperCount);

    const interrupted = papers.nth(1), interruptedId = await interrupted.getAttribute("data-paper-id");
    await interrupted.scrollIntoViewIfNeeded();
    const interruptedBox = await interrupted.locator("circle").first().boundingBox();
    const x = interruptedBox.x + interruptedBox.width / 2, y = interruptedBox.y + interruptedBox.height / 2;
    await page.mouse.move(x, y); await page.mouse.down();
    const ownedPosition = await interrupted.getAttribute("transform");
    await svg.dispatchEvent("pointerdown", { pointerId: 999, clientX: x + 80, clientY: y + 80 });
    await svg.dispatchEvent("pointercancel", { pointerId: 999 });
    await svg.dispatchEvent("pointermove", { pointerId: 999, clientX: x + 80, clientY: y + 80 });
    await svg.dispatchEvent("pointerup", { pointerId: 999 });
    check("foreign pointer cannot move or end the owned session", (await interrupted.getAttribute("transform")) === ownedPosition);
    await page.mouse.move(x + 25, y + 20, { steps: 3 });
    check("owner remains active after foreign pointer events", (await interrupted.getAttribute("transform")) !== ownedPosition);
    await interrupted.dispatchEvent("pointercancel", { pointerId: 1 });
    await page.mouse.move(1, 1); await page.mouse.up();
    await interrupted.click();
    check("cancel preserves the next genuine click", (await page.locator(".graph-node.paper.selected").getAttribute("data-paper-id")) === interruptedId);
    const hasSelection = await page.evaluate(() => Boolean(window.WORKSPACE_VIEW?.literature_selection));
    if (!hasSelection) {
      await page.locator("select").filter({ has: page.locator("option", { hasText: "All indexed records" }) }).selectOption({ label: "All indexed records" });
    }
    const downloadPromise = page.waitForEvent("download");
    if (hasSelection) {
      await page.getByRole("link", { name: "Original bibliography", exact: true }).first().click();
    } else {
      await page.getByRole("button", { name: "Export canonical .bib", exact: true }).click();
    }
    const download = await downloadPromise;
    const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "literature-graph-"));
    const downloadedBib = path.join(temporary, "references.bib");
    await download.saveAs(downloadedBib);
    check(
      "full BibTeX export preserves canonical bytes",
      fs.readFileSync(downloadedBib).equals(fs.readFileSync(path.join(path.dirname(viewPath), "references.bib"))),
    );
    assert(path.dirname(path.resolve(temporary)) === path.resolve(os.tmpdir()));
    assert(path.basename(temporary).startsWith("literature-graph-"));
    fs.rmSync(temporary, { recursive: true, force: true });
    check("no browser errors", errors.length === 0);
    check("no external requests", externalRequests.length === 0);
    console.log(JSON.stringify({ status: "PASS", checks, paperCount, errors, externalRequests }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
