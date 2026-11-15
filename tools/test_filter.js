// Drive site/filter.js through a minimal DOM stub: node tools/test_filter.js
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");

function element(props = {}) {
  const listeners = {};
  return {
    hidden: false,
    textContent: "",
    dataset: {},
    children: [],
    ...props,
    addEventListener(type, fn) { listeners[type] = fn; },
    fire(type) { listeners[type](); },
    querySelectorAll(selector) {
      const attr = selector.match(/^\[data-(.+)\]$/);
      const all = [];
      const walk = (el) => el.children.forEach((c) => { all.push(c); walk(c); });
      walk(this);
      const key = attr[1].replace(/-(.)/g, (_, c) => c.toUpperCase());
      return all.filter((c) => key in c.dataset);
    },
  };
}

function item(text) {
  return element({ dataset: { filter: text } });
}

const loaded = {};
global.document = {
  ids: {},
  getElementById(id) { return this.ids[id]; },
  addEventListener(type, fn) { loaded[type] = fn; },
  querySelectorAll() { return []; },
};
const { setUpFilter, fold } = require(path.join(__dirname, "..", "site", "filter.js"));
assert.equal(typeof loaded.DOMContentLoaded, "function", "filter.js waits for DOMContentLoaded");

const sec = element({ dataset: { filterSection: "" } });
const sec2 = element({ dataset: { filterSection: "" } });
const a = item("robert sparks simple stir");
const b = item("adam roach xcon");
const c = item("juan-carlos zuniga intdir");
sec.children = [a, b];
sec2.children = [c];
const list = element({ children: [sec, sec2] });
const count = element();
document.ids = { list, count };
const input = element({ value: "", dataset: { filterTarget: "list", filterCount: "count" } });
setUpFilter(input);

input.value = "Zúñiga";
input.fire("input");
assert.deepEqual([a.hidden, b.hidden, c.hidden], [true, true, false], "accents are ignored");
assert.equal(sec.hidden, true, "a section with no visible items hides");
assert.equal(sec2.hidden, false);
assert.equal(count.textContent, "1 of 3");

input.value = "sparks stir";
input.fire("input");
assert.deepEqual([a.hidden, b.hidden, c.hidden], [false, true, true], "every word must match");

input.value = "  ";
input.fire("input");
assert.deepEqual([a.hidden, b.hidden, c.hidden], [false, false, false], "an empty filter shows everything");
assert.equal(count.textContent, "");
assert.equal(fold("Ériç"), "eric");
console.log("filter.js: all checks passed");
