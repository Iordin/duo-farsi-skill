# Code Patterns

Copy-ready implementations. All comments in English, all user-visible strings in Persian.
Adapt names, do not relax the rules. Model: **TRANSLATE_REPLACE** (swap the text node,
preserve the element).

---

## shared/normalize.js — the single source of truth for keys

```js
// shared/normalize.js
// One normalizer for the whole project. scripts/normalize_dict.py must implement
// exactly the same steps, or cache keys will not match.
function normalizeKey(text) {
  if (text == null) return '';
  return String(text)
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, ' ')       // collapse whitespace (newlines, tabs, NBSP)
    .trim()
    .replace(/[^\p{L}\p{N} ]/gu, '') // strip punctuation
    .replace(/\s+/g, ' ')
    .trim();
}
```

---

## shared/storage.js — enabled + unknown_queue

```js
// shared/storage.js
const MAX_QUEUE = 500;

// In-memory mirror of the persisted toggle. Never trust a cached copy alone.
const state = { enabled: true };

function readEnabled() {
  return new Promise((resolve) => {
    chrome.storage.local.get({ enabled: true }, (res) => {
      state.enabled = !!res.enabled;
      resolve(state.enabled);
    });
  });
}

// Live updates: the user flips the popup switch, every tab reacts immediately.
function watchEnabled(onChange) {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes.enabled) return;
    state.enabled = !!changes.enabled.newValue;
    onChange(state.enabled);
  });
}

function setEnabled(next) {
  chrome.storage.local.set({ enabled: !!next });
}

// Offline "missing translation" log. Never leaves the device.
function queueUnknown(normalizedKey) {
  if (!normalizedKey) return;
  chrome.storage.local.get({ unknown_queue: [] }, (res) => {
    const queue = res.unknown_queue.slice();
    if (queue.includes(normalizedKey)) return;
    queue.push(normalizedKey);
    chrome.storage.local.set({ unknown_queue: queue.slice(-MAX_QUEUE) });
  });
}

function readUnknownQueue() {
  return new Promise((resolve) => {
    chrome.storage.local.get({ unknown_queue: [] }, (res) => resolve(res.unknown_queue));
  });
}
```

---

## dictionary.js — load, lookup, cache, queue

```js
// dictionary.js
// Offline dictionary: a flat JSON bundled with the extension. No network access.
const DICTIONARY_URL = chrome.runtime.getURL('dictionaries/dict-en-fa.json');

const index = new Map(); // normalized key -> Persian string

// Load once at startup. This reads a packaged local file, it is NOT a network call.
async function loadDictionary() {
  const res = await fetch(DICTIONARY_URL);
  const raw = await res.json();
  for (const [key, value] of Object.entries(raw)) {
    index.set(normalizeKey(key), value);
  }
  return index.size;
}

// Returns the Persian string, or null on a miss (caller queues the key).
function lookup(text) {
  return index.get(normalizeKey(text)) || null;
}
```

If the dictionary is small and you want zero `fetch` in the codebase, ship it as
`dictionaries/dict-en-fa.js` with `const RAW_DICTIONARY = { ... };` and drop `loadDictionary`'s
fetch entirely — that is the safest option for rule 2.

---

## classifier.js — decide, then extract

```js
// classifier.js
// Decides whether an element is in the TRANSLATE_REPLACE zone or the NEVER_TOUCH zone.
// The deny list is checked FIRST, before any dictionary lookup.
const classifyCache = new WeakMap(); // element -> 'skip' | { key, fa, node }

function isProtected(el) {
  if (!(el instanceof HTMLElement)) return true;
  if (el.closest('input, textarea, select, [contenteditable="true"]')) return true;
  if (el.closest(NEVER_TRANSLATE_SELECTOR)) return true;   // selectors.json -> joined list
  if (el.classList.contains('duo-fa-replaced')) return true; // already handled
  return false;
}

function classify(el) {
  if (classifyCache.has(el)) return classifyCache.get(el);

  let result = 'skip';
  if (!isProtected(el)) {
    const node = firstTextNode(el);
    if (node) {
      const key = normalizeKey(node.nodeValue || '');
      if (key && key.length <= MAX_KEY_LENGTH) {
        const fa = dictionary.lookup(key);
        result = fa ? { key, fa, node } : (queueUnknown(key), 'skip');
      }
    }
  }
  classifyCache.set(el, result);
  return result;
}

function firstTextNode(el) {
  for (const child of el.childNodes) {
    if (child.nodeType === Node.TEXT_NODE && child.nodeValue.trim()) return child;
  }
  return null;
}
```

`NEVER_TRANSLATE_SELECTOR` is built once from `selectors.json`:

```js
const NEVER_TRANSLATE_SELECTOR = SELECTORS.neverTranslate.join(', ');
```

---

## renderer.js — swap the text node, mark, never destroy

```js
// renderer.js
// TRANSLATE_REPLACE: replaces the TEXT NODE content with Persian. The element itself
// is never destroyed or re-created (rule 6). React may revert the text; the observer
// re-applies. Toggle-off does NOT restore original text (rule 11); reload to see it.
const REPLACE_CLASS = 'duo-fa-replaced';

function replaceText(el, faText, node) {
  if (!state.enabled) return;
  if (!faText || !node) return;

  // Already replaced and still Persian? Skip to avoid loops and redundant writes.
  if (el.classList.contains(REPLACE_CLASS) &&
      (node.nodeValue || '').trim() === faText.trim()) return;

  node.nodeValue = faText; // swap text node content; element preserved (rule 6)
  el.classList.add(REPLACE_CLASS);
  el.dir = 'rtl';
  el.lang = 'fa';
}

// Toggle off: stop translating. Existing replaced text stays Persian until reload.
// (No restoration of original text — agreed behavior, rule 11.)
function stop() { /* engine.disconnect handled in engine.js */ }
```

Companion CSS (`src/content/content.css`):

```css
.duo-fa-replaced {
  direction: rtl;
  unicode-bidi: isolate; /* keep RTL text from reordering the parent line */
}
```

Keep styles minimal. Do not override font-size/color/weight aggressively — the gloss
should look like the original UI, only Persian.

---

## engine.js — MutationObserver + debounced scan

```js
// engine.js
// Duolingo is a React SPA: screens mount/unmount constantly and React may revert text
// in place. Observe document.body (childList + characterData + subtree) and re-scan
// debounced. Skip mutations inside .duo-fa-replaced to avoid feedback loops.
const SCAN_DEBOUNCE_MS = 150;
let observer = null;
let timer = null;

function scheduleScan() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(scan, SCAN_DEBOUNCE_MS);
}

function scan() {
  timer = null;
  if (!state.enabled) return;
  const candidates = document.querySelectorAll(SELECTORS.translate.join(', '));
  for (const el of candidates) {
    const verdict = classify(el);
    if (verdict !== 'skip') renderer.replaceText(el, verdict.fa, verdict.node);
  }
}

function start() {
  scan(); // first pass
  observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      const t = m.target instanceof HTMLElement ? m.target : null;
      if (t && t.closest('.duo-fa-replaced')) continue; // rule 10: skip our own writes
    }
    scheduleScan();
  });
  observer.observe(document.body, {
    childList: true,
    characterData: true, // catch React reverting text in place
    subtree: true,
  });
}

function stop() {
  if (observer) { observer.disconnect(); observer = null; }
  if (timer) { clearTimeout(timer); timer = null; }
}
```

---

## index.js — boot

```js
// index.js
(async function boot() {
  await loadDictionary();
  await readEnabled();

  watchEnabled((enabled) => {
    if (enabled) { start(); }
    else { stop(); } // replaced text stays Persian until reload (rule 11)
  });

  if (state.enabled) start();
})();
```

---

## popup.html / popup.js — Persian UI, rtl

```html
<!DOCTYPE html>
<html dir="rtl" lang="fa">
  <head>
    <meta charset="utf-8" />
    <link rel="stylesheet" href="popup.css" />
  </head>
  <body>
    <h1>ترجمه‌های فارسی</h1>
    <label class="switch">
      <input type="checkbox" id="toggle" />
      <span id="status">روشن</span>
    </label>
    <p id="queue-info">رشته‌های ناشناس: ۰</p>
    <script src="popup.js"></script>
  </body>
</html>
```

```js
// popup.js
const toggle = document.getElementById('toggle');
const status = document.getElementById('status');
const queueInfo = document.getElementById('queue-info');

const ON = 'روشن';
const OFF = 'خاموش';

function paint(enabled) {
  toggle.checked = enabled;
  status.textContent = enabled ? ON : OFF; // textContent, Persian label
}

chrome.storage.local.get({ enabled: true }, (res) => paint(res.enabled));

toggle.addEventListener('change', () => {
  chrome.storage.local.set({ enabled: toggle.checked });
});

// Keep the popup in sync if the flag changes elsewhere.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.enabled) paint(!!changes.enabled.newValue);
});

readUnknownQueue().then((q) => {
  queueInfo.textContent = 'رشته‌های ناشناس: ' + q.length;
});
```

Popup strings are Persian and built with `textContent` — the same rule 3 discipline applies
to the extension's own UI.

---

## Floating toggle (optional)

If a floating on-page control is added:
- Root element: `dir="rtl"`, `lang="fa"`, label `ترجمه‌ها`.
- Created with `createElement`, label via `textContent`.
- Clicking it calls `setEnabled(next)` from `shared/storage.js`; the content script reacts
  through `storage.onChanged` — never by directly re-writing the DOM in the click handler.
- Position with `position: fixed` and a high `z-index`; it must not overlap choice cards
  or sentence tiles (rule 5): keep it out of any `[data-test*="challenge"]` container.
