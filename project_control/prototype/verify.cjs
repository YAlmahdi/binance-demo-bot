/* Prototype-only checks: read only this directory; no project suite or real evidence. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { pathToFileURL } = require("node:url");
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "styles.css"), "utf8");
const fixtureSource = fs.readFileSync(path.join(__dirname, "mock-data.js"), "utf8");
const appSource = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
let passed = 0;
function test(name, check) { check(); passed++; console.log("PASS " + name); }
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.hidden = false; this.open = false; this._text = ""; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; this._text = ""; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
}
function setup(source = fixtureSource) {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element("div")]));
  const navigation = Array.from({ length: 5 }, () => new Element("a"));
  const document = { createElement: tag => new Element(tag), getElementById: id => elements.get(id), querySelectorAll: () => navigation };
  const context = vm.createContext({ window: {}, document });
  if (source) vm.runInContext(source, context);
  vm.runInContext(appSource, context);
  return { elements, navigation, api: context.window.ProjectControlPrototype, data: context.window.PROJECT_CONTROL_MOCK };
}
function clone(data) { return JSON.parse(JSON.stringify(data)); }
function descendants(element, tag) {
  return element.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...descendants(child, tag)]);
}
const displayIds = ["freshness-data", "health-grid", "roadmap-list", "current-data", "latest-data", "decision-data"];
function offlineChecks() {
  const { data, api, elements, navigation } = setup();
  test("v3 fixture is explicit MOCK DATA and deeply frozen", () => {
    assert.equal(api.validate(data), data);
    assert.equal(data.schemaVersion, 3);
    assert(Object.isFrozen(data.roadmap[1].components[0].steps[0]));
    assert(data.latest.verification.startsWith("MOCK ONLY:"));
    assert(data.freshness.sourceSha.startsWith("MOCK-"));
    assert(!/[a-f0-9]{40}/i.test(fixtureSource));
  });
  test("Project Health is primary; five sections replace timeline and controls", () => {
    const sections = [...html.matchAll(/<section id="([^"]+)"/g)].map(match => match[1]);
    assert.deepEqual(sections, ["health", "roadmap", "current", "latest", "decision"]);
    assert.equal((html.match(/<nav>/g) || []).length, 1);
    assert(!/activity|timeline|filterActivity|activity-search|activity-status/i.test(html + appSource + fixtureSource + css));
    assert(!/<(?:input|select|button|form)\b/i.test(html));
  });
  test("six health cards each expose four evidence categories", () => {
    const cards = elements.get("health-grid").children;
    assert.equal(cards.length, 6);
    for (const card of cards) {
      const details = descendants(card, "details");
      assert.equal(details.length, 1);
      assert.equal(details[0].children[0].textContent, "Evidence & Gaps");
      assert.deepEqual(descendants(details[0], "dt").map(node => node.textContent), ["Built / Tested · MOCK", "Missing", "Blocked", "Evidence Limitations"]);
    }
  });
  test("compact roadmap exposes five readiness fields and nested substeps", () => {
    assert.equal(elements.get("roadmap-list").children.length, 5);
    for (const stage of elements.get("roadmap-list").children) {
      const detail = stage.children[1];
      assert.equal(detail.open, false);
      assert.deepEqual(descendants(detail, "dt").map(node => node.textContent), ["Built", "Tested", "Missing", "Blocked", "Next"]);
      assert(descendants(detail, "details").length >= 1);
      assert(descendants(detail, "li").length >= 1);
    }
    assert.equal(new Set(data.roadmap.map(item => item.phase)).size, 5);
  });
  test("current milestone references only the active development area", () => {
    const active = data.roadmap.find(item => item.status === "active");
    assert(elements.get("current-data").textContent.includes(active.title));
    assert.equal(descendants(elements.get("current-data"), "li").length, 3);
    assert(elements.get("current-data").textContent.includes("Building"));
    assert(elements.get("current-data").textContent.includes("Unresolved"));
    assert(elements.get("current-data").textContent.includes("Completion Requirements"));
  });
  test("component status is visible before optional detail and summaries stay concise", () => {
    const components = descendants(elements.get("roadmap-list"), "details").filter(item => item.className === "component-details");
    assert.equal(components.length, 6);
    for (const component of components) {
      const summary = component.children[0];
      assert.equal(summary.tagName, "summary");
      assert.equal(summary.children[0].className, "component-title");
      assert(summary.children[1].className.startsWith("badge "));
      assert.equal(component.open, false);
    }
    for (const milestone of data.roadmap) for (const value of Object.values(milestone.readiness)) assert(value.length <= 55);
  });
  test("latest update separates verification, five impacts and technical detail", () => {
    const latest = elements.get("latest-data");
    assert.equal(descendants(latest, "details").length, 2);
    assert.equal(descendants(latest, "code").length, 3);
    for (const category of ["Engineering", "AI/ML", "Strategy", "Financial Performance", "Risk"]) assert(latest.textContent.includes(category));
    assert(latest.textContent.includes("MOCK ONLY:"));
  });
  test("exactly one proposed approval-dependent decision", () => {
    assert.equal(descendants(elements.get("decision-data"), "h3").length, 1);
    assert.equal(data.decision.status, "approval");
    assert(elements.get("decision-data").textContent.includes("Approval Required"));
    assert(!Array.isArray(data.decision));
  });
  test("freshness is explicitly fictional; publication is never inferred", () => {
    const first = elements.get("freshness-data").textContent;
    assert(first.includes("Last Verified Update · MOCK"));
    assert(first.includes("Source SHA · MOCK"));
    assert(first.includes("Local / Unverified"));
    const changed = clone(data);
    changed.health[0].status = "built";
    changed.roadmap[0].status = "planned";
    api.render(changed);
    assert.equal(elements.get("freshness-data").textContent, first);
    api.render(data);
  });
  test("English headings and LTR technical text coexist with RTL Arabic", () => {
    assert(html.includes('<html lang="en" dir="rtl">'));
    assert.equal(descendants(elements.get("latest-data"), "code").every(node => node.dir === "ltr"), true);
    assert.equal(descendants(elements.get("health-grid"), "h3").every(node => node.dir === "ltr"), true);
    assert.equal(descendants(elements.get("health-grid"), "dd").every(node => node.dir === "rtl" && node.lang === "ar"), true);
    assert(!/[\u0600-\u06ff]/.test(Object.keys(data.roadmap[0].readiness).join("")));
    assert(![...html.matchAll(/<h[12][^>]*>([^<]+)/g)].some(match => /[\u0600-\u06ff]/.test(match[1])));
  });
  test("HTML, script-like content and paths render as literal text", () => {
    const hostile = clone(data);
    const payload = '</script><img src=x onerror="alert(1)"><script>alert(2)</script>';
    hostile.health[0].limitations = payload;
    hostile.roadmap[1].components[0].steps[0].description = payload;
    hostile.latest.technical[0] = payload;
    hostile.latest.changed = payload;
    assert.equal(api.render(hostile), true);
    assert(descendants(elements.get("health-grid"), "dd").some(node => node.textContent === payload && !node.children.length));
    assert.equal(descendants(elements.get("latest-data"), "code")[0].textContent, payload);
    assert.equal(descendants(elements.get("roadmap-list"), "img").length, 0);
    api.render(data);
  });
  test("schema rejects malformed, missing and contradictory fields", () => {
    const badCases = [undefined, null, [], { ...clone(data), mock: false }, { ...clone(data), schemaVersion: 1 }];
    const mutations = [
      value => { value.activity = []; },
      value => { value.health[0].category = "Other"; },
      value => { value.health[1].category = value.health[0].category; },
      value => { delete value.health[0].limitations; },
      value => { value.health[0].status = "profitable"; },
      value => { value.roadmap[1].readiness.built = ""; },
      value => { value.roadmap[1].status = "complete"; },
      value => { value.roadmap[0].status = "active"; },
      value => { value.roadmap[1].id = value.roadmap[0].id; },
      value => { value.current.milestoneId = "mock-foundation"; },
      value => { value.roadmap[3].phase = "Engineering"; },
      value => { value.roadmap[0].components = []; },
      value => { delete value.roadmap[0].components[0].status; },
      value => { value.roadmap[0].components[0].status = "approved"; },
      value => { value.roadmap[0].components[0].steps[0].status = "approved"; },
      value => { value.roadmap[0].components[0].steps[0].description = 7; },
      value => { value.latest.impacts.pop(); },
      value => { value.latest.verification = "PASS: actual project tests"; },
      value => { value.latest.technical = []; },
      value => { value.latest.technical[0] = "x".repeat(3001); },
      value => { value.decision = [value.decision, value.decision]; },
      value => { value.decision.status = "complete"; },
      value => { value.freshness.lastVerifiedUpdate = "2032-02-30T09:30:00Z"; },
      value => { value.freshness.lastVerifiedUpdate = "2032-06-04"; },
      value => { value.freshness.sourceSha = "a".repeat(40); },
      value => { value.freshness.publishedState = "Confirmed by tests"; }
    ];
    for (const mutate of mutations) { const value = clone(data); mutate(value); badCases.push(value); }
    for (const bad of badCases) {
      assert.equal(api.render(bad), false);
      assert.equal(elements.get("data-error").hidden, false);
      for (const id of displayIds) assert.equal(elements.get(id).children.length, 0);
    }
    assert.equal(api.render(data), true);
    assert.equal(elements.get("data-error").hidden, true);
  });
  test("missing fixture fails closed without substitute project status", () => {
    const missing = setup("");
    assert.equal(missing.elements.get("data-error").hidden, false);
    for (const id of displayIds) assert.equal(missing.elements.get(id).children.length, 0);
  });
  test("repeat rendering is deterministic and preserves fixture", () => {
    const before = JSON.stringify(data);
    const first = displayIds.map(id => elements.get(id).textContent);
    api.render(data);
    assert.deepEqual(displayIds.map(id => elements.get(id).textContent), first);
    assert.equal(JSON.stringify(data), before);
  });
  test("navigation targets are internal, local assets exist and selection updates", () => {
    for (const match of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
      const target = match[1];
      if (target.startsWith("#")) assert(html.includes('id="' + target.slice(1) + '"'));
      else { assert(["styles.css", "mock-data.js", "app.js"].includes(target)); assert(fs.existsSync(path.join(__dirname, target))); }
    }
    navigation[2].listeners.click();
    assert.equal(navigation[2].attributes["aria-current"], "location");
    assert.equal(navigation[0].attributes["aria-current"], undefined);
  });
  test("no network dependencies, unsafe DOM, storage or operations", () => {
    assert(!/https?:|@import|url\s*\(/i.test(html + css + fixtureSource + appSource));
    assert(!/\b(innerHTML|outerHTML|insertAdjacentHTML|eval|fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|localStorage|sessionStorage|indexedDB|serviceWorker)\b/.test(appSource + fixtureSource));
    assert(!/\b(import|require)\s*\(|\bdocument\.(write|cookie)\b/.test(appSource + fixtureSource));
    assert(!/<(?:iframe|object|embed|img|form|button)\b/i.test(html));
    assert(html.includes("connect-src 'none'"));
    assert(html.includes("form-action 'none'"));
  });
  test("native disclosures, skip link, focus and responsive support exist", () => {
    assert(html.includes('class="skip-link"'));
    assert(css.includes(":focus-visible"));
    assert(css.includes("prefers-reduced-motion"));
    assert(css.includes("@media(max-width:760px)"));
    assert(css.includes("@media(max-width:480px)"));
    assert(appSource.includes('node("details"'));
    assert(appSource.includes('node("summary"'));
  });
  console.log(passed + " offline check groups passed. DOM-double checks are not visual verification.");
}
async function browserChecks(modulePath, channel) {
  const { chromium } = require(modulePath);
  if (channel && !["chrome", "msedge"].includes(channel)) throw new Error("Use an already installed chrome/msedge channel");
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const nonlocal = [];
    const errors = [];
    page.on("request", request => { if (!request.url().startsWith("file://")) nonlocal.push(request.url()); });
    page.on("pageerror", error => errors.push(error.message));
    await context.route(/^(?!file:).*/, route => route.abort());
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(pathToFileURL(path.join(__dirname, "index.html")).href);
    assert.equal(await page.locator(".health-card").count(), 6);
    assert.equal(await page.locator(".stage").count(), 5);
    assert.equal(await page.locator("input, select, button, form, #activity").count(), 0);
    assert.equal(await page.locator("#decision-data h3").count(), 1);
    for (let i = 0; i < 6; i++) {
      const summary = page.locator(".health-details > summary").nth(i);
      await summary.focus(); await page.keyboard.press("Enter");
      assert.equal(await page.locator(".health-details").nth(i).evaluate(element => element.open), true);
      assert.equal(await page.locator(".health-details").nth(i).locator("dt").count(), 4);
    }
    for (let i = 0; i < 5; i++) {
      const summary = page.locator(".milestone-details > summary").nth(i);
      await summary.focus(); await page.keyboard.press("Enter");
      assert.equal(await page.locator(".milestone-details").nth(i).evaluate(element => element.open), true);
      assert.equal(await page.locator(".readiness-grid").nth(i).locator("dt").count(), 5);
    }
    for (const summary of await page.locator(".component-details > summary").all()) {
      assert.equal(await summary.locator(".badge").isVisible(), true);
      await summary.focus(); await page.keyboard.press("Space");
      assert.equal(await summary.evaluate(element => element.parentElement.open), true);
    }
    for (const summary of await page.locator("#latest details > summary").all()) {
      await summary.focus(); await page.keyboard.press("Enter");
      assert.equal(await summary.evaluate(element => element.parentElement.open), true);
    }
    assert.equal(await page.locator("#latest .technical-details code").first().evaluate(element => getComputedStyle(element).direction), "ltr");
    assert.equal(await page.locator("#health h3").first().evaluate(element => getComputedStyle(element).direction), "ltr");
    assert.equal(await page.locator("#health dd").first().evaluate(element => getComputedStyle(element).direction), "rtl");
    assert.equal(await page.locator("#health dd").first().getAttribute("lang"), "ar");
    assert.equal(await page.locator("#freshness-data code").first().evaluate(element => getComputedStyle(element).direction), "ltr");
    for (const summary of await page.locator(".health-details > summary, .milestone-details > summary").all()) {
      await summary.focus(); await page.keyboard.press("Enter");
      assert.equal(await summary.evaluate(element => element.parentElement.open), false);
    }
    for (const href of ["#health", "#roadmap", "#current", "#latest", "#decision"]) {
      await page.locator('nav a[href="' + href + '"]').click();
      assert.equal(new URL(page.url()).hash, href);
    }
    await page.evaluate(() => {
      const data = JSON.parse(JSON.stringify(window.PROJECT_CONTROL_MOCK));
      data.latest.changed = '<img src=x onerror="alert(1)">';
      data.health[0].limitations = '<script>alert(1)</script>';
      window.ProjectControlPrototype.render(data);
    });
    assert.equal(await page.locator("#latest img, #health script").count(), 0);
    assert((await page.locator("#latest dd").first().textContent()).includes("<img"));
    await page.evaluate(() => window.ProjectControlPrototype.render(window.PROJECT_CONTROL_MOCK));
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.evaluate(() => document.querySelectorAll("details").forEach(element => { element.open = false; }));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "Collapsed overflow at " + width);
      // Expand every detail to exercise long technical strings, nested grids and Arabic.
      await page.evaluate(() => document.querySelectorAll("details").forEach(element => { element.open = true; }));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "Expanded overflow at " + width);
      assert.equal(await page.locator(".health-card").count(), 6);
      const readability = await page.evaluate(() => {
        const nodes = document.querySelectorAll(".health-detail, .health-details dd, .readiness-grid dd, .substeps p, #current dd, #latest dd");
        return [...nodes].every(element => {
          const style = getComputedStyle(element);
          return parseFloat(style.fontSize) >= 15 && parseFloat(style.lineHeight) / parseFloat(style.fontSize) >= 1.65 && style.direction === "rtl";
        });
      });
      assert.equal(readability, true, "Explanation typography at " + width);
      assert.equal(await page.locator(".health-detail").first().evaluate(element => getComputedStyle(element).minHeight), "0px");
      const compactRows = await page.locator(".readiness-grid").nth(1).evaluate(element => {
        return getComputedStyle(element).display === "block" && [...element.children].every(row => getComputedStyle(row).display === "grid");
      });
      assert.equal(compactRows, true, "Compact roadmap summary at " + width);
      const contrast = await page.evaluate(() => {
        const channels = color => color.match(/[\d.]+/g).map(Number);
        const luminance = color => {
          const rgb = channels(color).slice(0, 3).map(value => {
            const normalized = value / 255;
            return normalized <= 0.04045 ? normalized / 12.92 : Math.pow((normalized + 0.055) / 1.055, 2.4);
          });
          return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
        };
        const nodes = document.querySelectorAll(".health-detail, .health-details dd, .readiness-grid dd, .substeps p, .health-card .badge, .component-details .badge");
        return Math.min(...[...nodes].map(element => {
          let ancestor = element;
          while (ancestor && channels(getComputedStyle(ancestor).backgroundColor)[3] === 0) ancestor = ancestor.parentElement;
          const foreground = luminance(getComputedStyle(element).color);
          const background = luminance(getComputedStyle(ancestor).backgroundColor);
          return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
        }));
      });
      assert(contrast >= 4.5, "Solid-background text contrast at " + width + ": " + contrast);
    }
    await page.evaluate(() => window.ProjectControlPrototype.render({ mock: false }));
    assert.equal(await page.locator("#data-error").isVisible(), true);
    assert.equal(await page.locator(".health-card").count(), 0);
    await page.reload();
    assert.equal(await page.locator(".health-card").count(), 6);
    assert.equal(await page.locator("details[open]").count(), 0);
    assert.deepEqual(nonlocal, []);
    assert.deepEqual(errors, []);
    console.log("PASS Chrome file:// loading; keyboard health/roadmap/substep/impact/technical disclosures; five navigation anchors; literal text safety; invalid-data recovery; reload reset.");
    console.log("PASS LTR headings/technical values and RTL Arabic; zero non-file requests/page errors; collapsed/expanded overflow checks at 1440, 1024, 768, 390, 320px.");
    console.log("PASS visible component statuses; explanation text >=15px with line height >=1.65; no fixed health explanation height; compact readiness rows at every requested width.");
    console.log("PASS sampled health/roadmap explanation and badge contrast >=4.5:1 against their solid backgrounds; not a full accessibility audit.");
    await context.close();
  } finally { await browser.close(); }
}
async function main() {
  offlineChecks();
  if (process.argv[2] === "--browser") {
    if (!process.argv[3]) throw new Error("Pass an existing Playwright module path");
    await browserChecks(process.argv[3], process.argv[4]);
  }
}
main().catch(error => { console.error("FAIL " + error.message); process.exitCode = 1; });
