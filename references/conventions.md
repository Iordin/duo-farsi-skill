# Conventions in Depth

Each rule below states what it forbids/requires, why, and the anti-pattern to watch for.
Rule numbers match `SKILL.md`. The model is **TWO-ZONE**: TRANSLATE_REPLACE swaps UI text
nodes; NEVER_TOUCH leaves learning content and inputs alone.

---

## Two-zone model (the foundation)

- **TRANSLATE_REPLACE zone** — source-language UI strings: instructions, buttons, feedback
  toasts, navigation labels, section/unit/lesson titles. Replace the **text node** with the
  Persian translation. The element is preserved.
- **NEVER_TOUCH zone** — target-language content and all form fields: exercise sentences,
  choice cards, sentence tiles, word banks, hint popups, audio transcripts, and
  `input`, `textarea`, `[contenteditable]`. Zero modification, regardless of language.

The boundary is enforced by `selectors.json` (`translate` vs `neverTranslate`) and by the
classifier's input/contenteditable guard. The deny list is checked **first**, before any
dictionary lookup.

---

## Rule 1 — MV3 only

**Requires** `manifest_version: 3`; statically declared content scripts; CSP
`script-src 'self'; object-src 'self'`.

**Forbids** remote code, dynamic remote script injection, host permissions beyond what
`content_scripts.matches` needs.

**Why**: offline + privacy. MV2 is deprecated; remote code is rejected in review.

---

## Rule 2 — Fully offline at runtime

**Requires** the dictionary to be packaged locally; load it via a bundled module or, only
where unavoidable, `fetch(chrome.runtime.getURL('dictionaries/dict-en-fa.json'))` — that is a
local file read, not a network call.

**Forbids** `fetch(http(s)://...)`, `XMLHttpRequest`, `WebSocket`, `EventSource`,
`navigator.sendBeacon`, remote `import()`, CDN, analytics, Google Fonts.

**Anti-pattern**: "fallback that fetches missing translations from an API." Never. Misses
go to `unknown_queue` (rule 4).

---

## Rule 3 — No `eval`; textContent/nodeValue only

**Requires**
- Set translated text by assigning `textContent` (on an element) or `nodeValue` (on a text
  node). Both are safe sinks.
- Build any wrapper structure with `createElement` + `appendChild`.

**Forbids** `eval`, `new Function`, `setTimeout("string")`, `document.write`,
`innerHTML`/`outerHTML`/`insertAdjacentHTML` where the value contains translated text or
DOM-derived text. (Clearing with `innerHTML = ''` is fine.)

**Why**: rule 3 + rule 6 together guarantee the extension can never corrupt the learning UI
or inject markup into Duolingo's DOM.

---

## Rule 4 — TRANSLATE_REPLACE zone

**Requires**
- Replace the **text node** content (`node.nodeValue = faText`) with the Persian string.
- If the normalized key is **not** in the dictionary, do **not** touch the element and push
  the normalized key to `unknown_queue`.

**Forbids**
- Appending a separate Persian span beneath the original (the old model).
- Rendering a placeholder (`[???]`, English echo) on a miss.
- Touching an element whose key is unknown "to be helpful".

**Why**: full UI localization; the English/Arabic original is not needed in the UI zone
(turn the extension off to see originals). Misses must be silent and queued for the
developer to grow the dictionary offline.

---

## Rule 5 — NEVER_TOUCH zone

Always skip, regardless of language:
- `input`, `textarea`, `select`, `[contenteditable="true"]`.
- Exercise sentences and prompts, challenge headers, "Translate this sentence",
  tap-the-pair tokens, listening prompts.
- Choice cards / answer option lists and anything inside them.
- Sentence tiles, word banks, drag-source chips.
- Hint popups, "Solution" / "Correct solution" panels, tips & notes bodies.
- Audio transcripts / subtitle regions.
- Coach/character speech bubbles, streak/notification toasts whose content is
  target-language practice.

**Implementation**: enforced in the classifier *before* any dictionary lookup:

```js
if (el.closest(NEVER_TRANSLATE_SELECTOR)) return; // always first
if (el.closest('input, textarea, select, [contenteditable="true"]')) return;
```

**Why**: translating exercises defeats the lesson and can leak answers.

---

## Rule 6 — Replace the text node only, preserve the element

**Requires**
- Locate the text node (walk `childNodes` for `Node.TEXT_NODE` with non-empty trimmed text).
- Set `node.nodeValue = faText`. Do not remove the element, do not `replaceChild` it, do not
  `appendChild`/`removeChild` the label.
- React owns the element and may re-render it, restoring the original text. That is expected:
  the `MutationObserver` (`characterData`) re-applies the translation.

**Forbids** `el.remove()`, `el.replaceWith(...)`, `el.outerHTML = ...`, re-creating the
label, or any operation that destroys the original element reference Duolingo holds.

**Why**: destroying elements breaks React's reconciliation, throws hydration/ownership
errors, and can crash the lesson screen.

---

## Rule 7 — Replaced nodes are marked

**Requires**
- Add class `duo-fa-replaced` to the element whose text node was swapped.
- Set `el.dir = 'rtl'` and `el.lang = 'fa'`.

```css
.duo-fa-replaced {
  direction: rtl;
  unicode-bidi: isolate; /* keep RTL text from reordering the parent line */
}
```

Keep styles minimal so Duolingo's own layout is not broken. Do **not** override font-size,
color, or weight aggressively; the gloss should look like the original UI, only Persian.

**Forbids** the old `duo-fa-translation` appended-span class and its block/muted styling.

---

## Rule 8 — Extension UI is Persian

`popup.html`, options page, floating toggle: `<html dir="rtl" lang="fa">`. Persian labels,
built with `textContent`. No English labels in the extension's own UI.

---

## Rule 9 — Dictionary: flat, normalized, en→fa (ar→fa-ready)

**Shape** — flat `{ "continue": "ادامه" }`. No nesting, no per-locale wrappers.

**Normalization** (one shared function, mirrored in `scripts/normalize_dict.py`):

```js
function normalizeKey(text) {
  return String(text)
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[^\p{L}\p{N} ]/gu, '') // strip punctuation
    .replace(/\s+/g, ' ')
    .trim();
}
```

V1 is **en→fa**. Keep the structure ready for **ar→fa**: the dictionary is keyed by the
normalized source string and valued in Persian, so an ar→fa dictionary is just another
flat file with Arabic keys. Do not hardcode the source language into the loader.

**Misses**: queue the **normalized** key to `unknown_queue`, de-duplicated, capped (~500).
Render nothing on a miss.

---

## Rule 10 — MutationObserver on document.body

**Requires**
- Observe `document.body` with `{ childList: true, characterData: true, subtree: true }`.
- `characterData` is required so React's in-place text reverts are caught and re-translated.
- Skip mutations whose target is inside `.duo-fa-replaced` (otherwise the observer fights
  its own writes and spins the CPU).
- Debounce mutation bursts (120–250 ms or `requestIdleCallback`).

**Forbids** polling with `setInterval`, a single pass on load, observing only a guessed
container, synchronous work inside the callback.

---

## Rule 11 — Global toggle

- `enabled` (boolean, default `true`) in `chrome.storage.local`.
- Content script reads it on startup and mirrors it via `chrome.storage.onChanged`:

```js
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !('enabled' in changes)) return;
  state.enabled = !!changes.enabled.newValue;
});
```

- Turning **off** stops the scanner. It does **not** restore original text on screen;
  replaced text stays Persian until the next page load. If the user wants the original
  back, they reload. (This is the agreed behavior — do not add restoration logic.)
- Turning **on** re-scans immediately.

**Forbids** storing the flag only in a module variable, in page `localStorage`, or in
`chrome.storage.sync`.

---

## Rule 12 — Languages

- Comments, log messages, variable names, commit messages: **English**.
- Anything rendered to a human via the extension's own UI: **Persian**.
- Dictionary values: Persian. Dictionary keys: the source string as it appears on the page
  (pre-normalization).
- No Chinese, Russian, or other languages anywhere in the repo unless the user explicitly
  asks for a translated doc as a separate file.
