import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { apply } from "../lib/index.js";

let provider;
const ctx = {
  skills: {
    registerProvider(factory) {
      provider = factory();
    },
  },
};

apply(ctx);
assert.ok(provider, "apply() must register a skill provider");
assert.equal(provider.name, "desktop-pilot");

const candidates = await provider.list();
assert.equal(candidates.length, 1);
const candidate = candidates[0];
assert.equal(candidate.name, "desktop-pilot");
assert.equal(candidate.provider, "desktop-pilot");
assert.ok(candidate.description.length > 20);
assert.ok(Number.isFinite(candidate.rank));
assert.ok(existsSync(candidate.locator), "locator must exist");
assert.ok(existsSync(candidate.resourceBase.path), "resource base must exist");

const loaded = await provider.get(candidate);
assert.equal(loaded.name, "desktop-pilot");
assert.ok(!loaded.content.startsWith("---"), "frontmatter must be stripped");
assert.ok(loaded.content.includes("Desktop Pilot"));
assert.ok(loaded.content.includes("dp.py"));
assert.ok(loaded.content.includes("本机入口"), "absolute runtime path must be injected");

const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL("../package.json", import.meta.url)), "utf8"),
);
assert.equal(pkg.name, "dsh-desktop-pilot");
assert.equal(pkg.dsh.bundle.patch, "./cordis.patch.yml");
assert.ok(existsSync(fileURLToPath(new URL("../cordis.patch.yml", import.meta.url))));

console.log("plugin_test: OK", {
  skill: candidate.name,
  rank: candidate.rank,
  resources: candidate.resourceBase.path,
  bytes: loaded.content.length,
});