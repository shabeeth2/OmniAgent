import assert from "node:assert/strict";

// Run against a live dev or production server; compilation alone cannot catch
// a stylesheet being served with unprocessed Tailwind directives.
const base = new URL(process.argv[2] ?? "http://127.0.0.1:3000");
const page = await fetch(base, { signal: AbortSignal.timeout(60000) });
assert.equal(page.status, 200, "The chat page must load");
const html = await page.text();
const links = [...html.matchAll(/<link\b[^>]*>/g)]
  .map(([tag]) => /rel="stylesheet"/.test(tag) ? tag.match(/href="([^"]+)"/)?.[1] : null)
  .filter(Boolean);
assert.ok(links.length, "The page must link a stylesheet");

let css = "";
for (const link of links) {
  const response = await fetch(new URL(link.replaceAll("&amp;", "&"), base), {
    headers: { Origin: base.origin },
    signal: AbortSignal.timeout(60000),
  });
  assert.equal(response.status, 200, `Stylesheet failed to load: ${link}`);
  assert.match(response.headers.get("content-type") ?? "", /text\/css/);
  css += await response.text();
}
assert.doesNotMatch(css, /@theme\s|@tailwind\s/, "Tailwind directives must be compiled");
for (const selector of ["flex", "sr-only", "h-dvh", "bg-background"]) {
  assert.ok(css.includes(`.${selector}`), `Missing Tailwind utility: ${selector}`);
}
console.log(`Styles verified: ${base.origin} (${links.length} stylesheet links)`);
