const fs = require("fs");
const path = require("path");
const { chromium } = require(
  path.join(process.env.CODEX_NODE_MODULES, "playwright")
);

const projectRoot = path.resolve(__dirname, "..");
const outputDir = path.join(projectRoot, "artifacts", "ui-qa");
const referencePath =
  "C:\\Users\\闫亚奇\\.codex\\generated_images\\019f93d0-4296-7c93-8df5-5e236ba4b202\\call_7S1fe9WeBcKmsopQGxCSGVAC.png";
const desktopPath = path.join(outputDir, "fluid-exchange-desktop.png");
const mobilePath = path.join(outputDir, "fluid-exchange-mobile.png");
const fullComparisonPath = path.join(outputDir, "comparison-full.png");
const focusComparisonPath = path.join(outputDir, "comparison-focus.png");

function imageDataUrl(filePath) {
  return `data:image/png;base64,${fs.readFileSync(filePath).toString("base64")}`;
}

async function captureComparison(browser, options) {
  const page = await browser.newPage({
    viewport: { width: 2880, height: options.height },
    deviceScaleFactor: 1,
  });
  const top = options.top || 0;
  await page.setContent(`
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          * { box-sizing: border-box; }
          html, body { width: 2880px; height: ${options.height}px; margin: 0; overflow: hidden; background: #020b17; }
          main { display: grid; grid-template-columns: 1440px 1440px; width: 2880px; height: ${options.height}px; }
          figure { position: relative; width: 1440px; height: ${options.height}px; margin: 0; overflow: hidden; }
          figure + figure { border-left: 2px solid #5af6dc; }
          img { position: absolute; left: 0; top: -${top}px; width: 1440px; height: 1024px; object-fit: cover; }
          figcaption { position: absolute; z-index: 2; left: 18px; top: 16px; padding: 8px 12px; border: 1px solid rgba(90,246,220,.5); border-radius: 999px; background: rgba(2,11,23,.84); color: #d9fff8; font: 600 13px/1 sans-serif; letter-spacing: .12em; }
        </style>
      </head>
      <body>
        <main>
          <figure><img src="${imageDataUrl(referencePath)}"><figcaption>REFERENCE</figcaption></figure>
          <figure><img src="${imageDataUrl(desktopPath)}"><figcaption>IMPLEMENTATION</figcaption></figure>
        </main>
      </body>
    </html>
  `);
  await page.waitForFunction(() =>
    Array.from(document.images).every((image) => image.complete)
  );
  await page.screenshot({ path: options.path });
  await page.close();
}

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
  });
  const consoleErrors = [];
  const pageErrors = [];
  const failedResponses = [];
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1024 },
    deviceScaleFactor: 1,
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });
  await page.goto("http://127.0.0.1:8765/", { waitUntil: "networkidle" });
  await page.locator('.sidebar [data-view="custom"]').click();
  await page.locator("#custom-formula-list .formula-item").first().waitFor();
  await page.locator("#custom-result-title").waitFor();
  await page.waitForTimeout(900);
  await page.screenshot({ path: desktopPath, fullPage: false });

  const desktopState = await page.evaluate(() => ({
    title: document.querySelector("#custom-result-title")?.textContent?.trim(),
    count: document.querySelector("#custom-match-count")?.textContent?.trim(),
    activeCard: document.querySelector(".formula-item.active h3")?.textContent?.trim(),
    strategyCards: document.querySelectorAll(".formula-item").length,
    visibleRows: document.querySelectorAll("#custom-results-table tbody tr").length,
    unresolvedLucide: document.querySelectorAll("i[data-lucide]").length,
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    lastCardFullyVisible: (() => {
      const list = document.querySelector("#custom-formula-list");
      const card = list?.lastElementChild;
      if (!list || !card) return false;
      return card.getBoundingClientRect().right <= list.getBoundingClientRect().right + 1;
    })(),
  }));

  const alternateButton = page.locator("#custom-formula-list .formula-item button").nth(1);
  const alternateName = (await alternateButton.locator("h3").textContent()).trim();
  await alternateButton.click();
  await page.waitForFunction(
    (name) => document.querySelector("#custom-result-title")?.textContent?.trim() === name,
    alternateName
  );
  const alternateStrategyWorked =
    (await page.locator("#custom-result-title").textContent()).trim() === alternateName;
  await page.locator("#custom-formula-list .formula-item button", {
    hasText: "放量突破缩量承接",
  }).click();
  await page.locator("#custom-search").fill("百合花");
  await page.waitForTimeout(120);
  const searchRows = await page.locator("#custom-results-table tbody tr").count();
  await page.locator("#custom-search").fill("");
  await page.locator("#custom-results-table [data-detail]").first().click();
  const drawerOpened = await page.locator("#stock-drawer").evaluate((node) =>
    node.classList.contains("open")
  );
  await page.locator("#drawer-close").click();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.mobile-nav [data-view="watchlist"]').click();
  await page.locator('.mobile-nav [data-view="custom"]').click();
  await page.waitForTimeout(450);
  await page.screenshot({ path: mobilePath, fullPage: false });
  const mobileState = await page.evaluate(() => ({
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    activeCardVisible: Boolean(document.querySelector(".formula-item.active")),
    titleVisible: Boolean(document.querySelector("#custom-result-title")),
    activeCenterDelta: (() => {
      const list = document.querySelector("#custom-formula-list");
      const card = list?.querySelector(".formula-item.active");
      if (!list || !card) return null;
      const listRect = list.getBoundingClientRect();
      const cardRect = card.getBoundingClientRect();
      return Math.round(
        (cardRect.left + cardRect.width / 2) -
        (listRect.left + listRect.width / 2)
      );
    })(),
  }));
  await page.close();

  await captureComparison(browser, {
    height: 1024,
    top: 0,
    path: fullComparisonPath,
  });
  await captureComparison(browser, {
    height: 560,
    top: 170,
    path: focusComparisonPath,
  });
  await browser.close();

  console.log(JSON.stringify({
    desktopPath,
    mobilePath,
    fullComparisonPath,
    focusComparisonPath,
    desktopState,
    mobileState,
    interactionState: {
      alternateStrategyWorked,
      searchRows,
      drawerOpened,
    },
    consoleErrors,
    pageErrors,
    failedResponses,
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
