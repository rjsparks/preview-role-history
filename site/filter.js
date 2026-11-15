// Filter a list as the reader types. Items carry data-filter with lower-cased,
// accent-free text; sections marked data-filter-section hide when empty.
"use strict";

function fold(text) {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

function setUpFilter(input) {
  const list = document.getElementById(input.dataset.filterTarget);
  const count = document.getElementById(input.dataset.filterCount);
  if (!list) return;
  const items = Array.from(list.querySelectorAll("[data-filter]"));
  const sections = Array.from(list.querySelectorAll("[data-filter-section]"));
  input.addEventListener("input", () => {
    const words = fold(input.value).split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const item of items) {
      const hit = words.every((w) => item.dataset.filter.includes(w));
      item.hidden = !hit;
      if (hit) shown += 1;
    }
    for (const section of sections) {
      section.hidden = !Array.from(section.querySelectorAll("[data-filter]")).some((i) => !i.hidden);
    }
    if (count) count.textContent = words.length ? `${shown} of ${items.length}` : "";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("input[data-filter-target]").forEach(setUpFilter);
});

if (typeof module !== "undefined") module.exports = { fold, setUpFilter };
