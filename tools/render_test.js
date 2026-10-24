#!/usr/bin/env node
/**
 * Render the built page in a real DOM and drive it the way a visitor would.
 *
 * Checking that the HTML parses is not the same as checking that the product
 * works. This loads site/index.html in jsdom, clicks the actual buttons, and
 * asserts on what appears in the results pane — so a broken filter, a broken
 * hash round-trip, or a template that silently lost its event listeners fails
 * here rather than in front of a user.
 *
 *   node tools/render_test.js
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const HTML = path.join(__dirname, "..", "site", "index.html");
const failures = [];
let checks = 0;

function check(name, cond, detail) {
  checks++;
  if (!cond) failures.push(`${name}${detail ? " — " + detail : ""}`);
}

function boot(hash = "") {
  const dom = new JSDOM(fs.readFileSync(HTML, "utf8"), {
    runScripts: "dangerously",
    url: "https://docket.example/" + hash,
    pretendToBeVisual: true,
  });
  return dom;
}

function label(dom, group) {
  return dom.window.document.querySelector(`[data-group="${group}"]`);
}

/** Click a chip by its visible text inside a group. */
function pick(dom, group, text) {
  const box = label(dom, group);
  const btn = [...box.querySelectorAll("button")].find(
    (b) => b.textContent.trim() === text
  );
  if (!btn) throw new Error(`no chip ${JSON.stringify(text)} in ${group}`);
  btn.click();
}

const items = (dom) => [...dom.window.document.querySelectorAll(".item")];
const count = (dom) => dom.window.document.getElementById("count").textContent;

// ---------------------------------------------------------------- boot
{
  const dom = boot();
  const d = dom.window.document;
  check("page boots without throwing", true);
  check("brand rendered", d.querySelector("h1").textContent === "Docket");
  check("markets chips built", label(dom, "markets").querySelectorAll("button").length === 3);
  check("products chips built", label(dom, "products").querySelectorAll("button").length === 5);
  check("size chips built", label(dom, "size").querySelectorAll("button").length === 4);
  check("starts empty", items(dom).length === 0);
  check("shows the empty prompt", d.querySelector(".empty") !== null);
  check("stamp rendered", /as of 2026-10-24/.test(d.getElementById("built").textContent),
        d.getElementById("built").textContent);
  check("upi string present", d.getElementById("upi").textContent === "chirag120670598-1@oksbi");
}

// ------------------------------------------------- one answer is not enough
{
  const dom = boot();
  pick(dom, "markets", "European Union");
  check("market alone renders nothing", items(dom).length === 0);
  check("hint still visible", dom.window.document.getElementById("hint").hidden === false);
  pick(dom, "products", "Software / SaaS");
  check("two answers render results", items(dom).length > 0);
  check("hint hidden once ready", dom.window.document.getElementById("hint").hidden === true);
}

// ------------------------------------------------------ EU software, small
{
  const dom = boot();
  pick(dom, "markets", "European Union");
  pick(dom, "products", "Software / SaaS");
  pick(dom, "size", "10–49");
  const n = items(dom).length;
  check("EU software small returns entries", n >= 5, `${n}`);
  check("count text agrees with rows", count(dom).startsWith(String(n)), count(dom));

  const text = dom.window.document.getElementById("results").textContent;
  check("CRA appears", text.includes("Cyber Resilience Act"));
  check("GDPR appears", text.includes("GDPR"));
  check("no Indian regimes leak in", !text.includes("Labour Codes"));
  check("no California regime leaks in", !text.includes("SB 54"));
  check("upsell-free: no paywall copy", !/subscribe|upgrade to (view|see)/i.test(text));

  const first = items(dom)[0];
  check("upcoming sorted before in-force",
        first.className.includes("upcoming"), first.className);
  const links = [...dom.window.document.querySelectorAll(".foot a")];
  check("every row links its source",
        links.length === items(dom).length, `${links.length} links / ${items(dom).length} rows`);
  check("source links open in a new tab", links.every((a) => a.rel.includes("noopener")));
}

// --------------------------------------------------- India does not see EU law
{
  const dom = boot();
  pick(dom, "markets", "India");
  pick(dom, "products", "Software / SaaS");
  const text = dom.window.document.getElementById("results").textContent;
  check("India gets labour codes", text.includes("Labour Codes"));
  check("India gets the EPF ceiling", text.includes("25,000"));
  check("India does not get the CRA", !text.includes("Cyber Resilience Act"));
  check("India does not get GDPR", !text.includes("GDPR"));
}

// ------------------------------------------------------- hardware in the EU
{
  const dom = boot();
  pick(dom, "markets", "European Union");
  pick(dom, "products", "Connected hardware");
  const text = dom.window.document.getElementById("results").textContent;
  check("hardware gets machinery", text.includes("Machinery"));
  check("hardware gets the CRA", text.includes("Cyber Resilience Act"));
}

// -------------------------------------------------------- services only
{
  const dom = boot();
  pick(dom, "markets", "European Union");
  pick(dom, "products", "Services only");
  const text = dom.window.document.getElementById("results").textContent;
  check("services get GDPR", text.includes("GDPR"));
  check("services do not get product safety law", !text.includes("Machinery"));
  check("services do not get the CRA reporting duty",
        !text.includes("Article 14 reporting duty"));
}

// ------------------------------------------------------------ California
{
  const dom = boot();
  pick(dom, "markets", "California");
  pick(dom, "products", "Physical goods");
  const text = dom.window.document.getElementById("results").textContent;
  check("California gets SB 54", text.includes("SB 54"));
  check("California gets nothing EU", !text.includes("Cyber Resilience Act"));
}

// ------------------------------------------------------- toggle off again
{
  const dom = boot();
  pick(dom, "markets", "European Union");
  pick(dom, "products", "Software / SaaS");
  const before = items(dom).length;
  pick(dom, "markets", "European Union"); // second click deselects
  check("deselecting a chip clears results", items(dom).length === 0, `was ${before}`);
  const pressed = label(dom, "markets").querySelector("button").getAttribute("aria-pressed");
  check("aria-pressed tracks state", pressed === "false", pressed);
}

// ------------------------------------------------------ hash round-trip
{
  const dom = boot("#m=IN&p=software&s=large");
  const d = dom.window.document;
  const pressed = [...label(dom, "markets").querySelectorAll("button")]
    .filter((b) => b.getAttribute("aria-pressed") === "true")
    .map((b) => b.textContent.trim());
  check("hash restores the market", pressed.join() === "India", pressed.join());
  check("hash restores results", items(dom).length > 0);
  check("hash state is written back to the URL", d.location.hash.includes("m=IN"), d.location.hash);

  const sizePressed = [...label(dom, "size").querySelectorAll("button")]
    .filter((b) => b.getAttribute("aria-pressed") === "true")
    .map((b) => b.textContent.trim());
  check("hash restores the headcount band", sizePressed.join() === "250+", sizePressed.join());
}

// ------------------------------------------------------------- .ics export
{
  const dom = boot();
  pick(dom, "markets", "European Union");
  pick(dom, "products", "Software / SaaS");

  let captured = null;
  dom.window.URL.createObjectURL = (blob) => {
    captured = blob;
    return "blob:test";
  };
  dom.window.URL.revokeObjectURL = () => {};
  dom.window.HTMLAnchorElement.prototype.click = function () {};
  dom.window.document.getElementById("ics").click();
  check("ics export produced a blob", captured !== null);
  if (captured) {
    check("ics blob has calendar mime",
          captured.type.startsWith("text/calendar"), captured.type);
  }
}

// ------------------------------------------------------------ no network
{
  const dom = boot();
  const d = dom.window.document;
  const external = [...d.querySelectorAll("[src],[href]")]
    .map((n) => n.getAttribute("src") || n.getAttribute("href"))
    .filter((u) => /^https?:\/\//.test(u) && !u.includes("github.com"));
  check("no external assets at load", external.length === 0, external.join(", "));
}

// ----------------------------------------------------------------- report
console.log(`render_test: ${checks - failures.length}/${checks} checks passed`);
if (failures.length) {
  for (const f of failures) console.log("  FAIL  " + f);
  process.exit(1);
}
console.log("  all good");
