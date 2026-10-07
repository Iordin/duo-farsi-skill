---
name: duo-ext-conventions
description: Conventions and hard constraints for duo-farsi, an offline Chrome MV3 extension that REPLACES source-language Duolingo UI text with Persian from a bundled JSON dictionary while leaving exercise, choice and hint content untouched. Use when generating, editing, reviewing or debugging project files, or extending the dictionary. Enforces a two-zone model - TRANSLATE_REPLACE swaps the text node of UI strings (element preserved, React-safe) and NEVER_TOUCH protects choice cards, sentence tiles, word banks, hint popups, audio transcripts, input, textarea and contenteditable. Offline-only MV3 with no fetch except chrome.runtime.getURL; no eval, nodeValue and textContent only; replaced nodes carry class duo-fa-replaced with dir=rtl; flat normalized dictionary en-to-fa (ar-to-fa ready) with misses queued to unknown_queue; MutationObserver on document.body with characterData skipping duo-fa-replaced; enabled toggle in chrome.storage.local with live storage.onChanged; English comments, Persian UI strings.
---

# duo-farsi Extension Conventions

## Overview

`duo-farsi` is an offline Chrome Extension (Manifest V3) that shows Persian in place of
source-language UI strings on duolingo.com. It ships an internal JSON dictionary and
performs **zero** network I/O at runtime. Every file in this project must obey the twelve
rules below; they are hard constraints, not preferences.

**Two-zone model.** The page is split into two zones:

- **TRANSLATE_REPLACE** — source-language UI strings (instructions, buttons, feedback,
  navigation, titles). The Persian translation **replaces the text node** of the element.
  The element itself is never destroyed or re-created.
- **NEVER_TOUCH** — target-language content (exercise sentences, choice cards, sentence
  tiles, word banks, hint popups, audio transcripts) and all `input`, `textarea`,
  `[contenteditable]`. Zero modification, regardless of language.

Two languages only: **English for code comments**, **Persian for any string a user sees**.
Never put Chinese (or any other language) into generated project files.

## Hard rules (non-negotiable)

| # | Rule | Practical meaning |
|---|------|-------------------|
| 1 | MV3 only | `manifest_version: 3`; content scripts declared statically; CSP `script-src 'self'`. |
| 2 | Fully offline at runtime | No `fetch` except `chrome.runtime.getURL` on a packaged local file. No `XMLHttpRequest`, `WebSocket`, remote `import()`, CDN, analytics, web fonts. |
| 3 | No `eval`; textContent/nodeValue only | No `eval`, `new Function`, `document.write`. Set translated text via `textContent` (on a text node, `nodeValue`). `innerHTML` may only take a static developer-authored literal — never dictionary data or DOM-derived text. |
| 4 | TRANSLATE_REPLACE zone | Replace the **text node** content with Persian. If the string is NOT in the dictionary, do not touch the element and push the normalized key to `unknown_queue`. |
| 5 | NEVER_TOUCH zone | Choice cards, sentence tiles, word banks, hint popups, audio transcripts, and all `input`, `textarea`, `[contenteditable]` are never modified, regardless of language. |
| 6 | Replace the text node only | Never destroy or re-create the element itself. React owns the element; it may re-render and restore the original text — the `MutationObserver` re-applies. |
| 7 | Replaced nodes are marked | Replaced elements get class `duo-fa-replaced` with `direction: rtl` (and `lang="fa"`) styling. |
| 8 | Extension UI is Persian | Popup, floating toggle, options: Persian strings with `dir="rtl"` (and `lang="fa"`). |
| 9 | Dictionary: flat, normalized, en→fa (ar-ready) | Flat JSON `{ "source": "ترجمه" }`, normalized keys (lowercase, trimmed, whitespace collapsed, punctuation stripped). V1 is en→fa; keep the structure ready for ar→fa. |
| 10 | MutationObserver on document.body | Observe `{ childList: true, characterData: true, subtree: true }`; skip nodes inside `.duo-fa-replaced`; debounce mutation bursts. |
| 11 | Global toggle | `chrome.storage.local` key `enabled` (boolean). All content-script behavior is gated on it and updates live via `chrome.storage.onChanged`. |
| 12 | Languages | Code comments in English; user-visible strings (extension UI + dictionary values) in Persian. |

## Workflow

1. **Identify the file** being created or changed, then load the matching reference:

   | Request | Load |
   |---|---|
   | Any of the 12 rules in depth, edge cases, rationale | `references/conventions.md` |
   | Project layout, manifest, data flow, storage schema | `references/architecture.md` |
   | Writing a module (renderer / engine / classifier / popup / dictionary) | `references/code-patterns.md` |
   | Reviewing or debugging existing code | `references/review-checklist.md` |
   | Adding dictionary entries or selectors | `assets/dict-en-fa.template.json`, `assets/selectors.template.json` |

2. **Write the code** using the canonical patterns in `references/code-patterns.md`. Do not invent
   new APIs or new storage keys.
3. **Validate** the result:
   - Rule scan: `python3 scripts/lint_rules.py <project-root>`
   - Dictionary hygiene: `python3 scripts/normalize_dict.py --check dict-en-fa.json`
4. **Self-check** against the checklist at the bottom before replying.

## Translation decision tree

```
Element found by the scanner
├─ Matches NEVER_TRANSLATE selectors or is inside one?      → skip
├─ input / textarea / [contenteditable]?                   → skip
├─ Choice card, sentence tile, word bank,
│  hint popup, audio transcript, or a token chip
│  inside a challenge?                                      → skip
├─ enabled === false?                                       → skip
├─ Already replaced AND current text already equals fa?    → skip
├─ Dictionary hit?                                         → replace text node, mark duo-fa-replaced
└─ Miss?                                                    → queue to unknown_queue, render nothing
```

When in doubt, **skip**. A missing translation is always better than a mistranslated
exercise — rule 5 violations break the learning flow.

## Canonical renderer (short form)

```js
// renderer.js — replaces the text node of a Duolingo UI string with Persian.
const REPLACE_CLASS = 'duo-fa-replaced';

function replaceText(el, faText) {
  if (!state.enabled) return;
  if (el.classList.contains(REPLACE_CLASS) &&
      (el.textContent || '').trim() === faText.trim()) return; // already done
  const node = firstTextNode(el);
  if (!node) return;
  node.nodeValue = faText; // swap text node content; element preserved (rule 6)
  el.classList.add(REPLACE_CLASS);
  el.dir = 'rtl';
  el.lang = 'fa';
}

function firstTextNode(el) {
  // Many Duolingo labels wrap text in a child span; walk childNodes for a real text node.
  for (const child of el.childNodes) {
    if (child.nodeType === Node.TEXT_NODE && child.nodeValue.trim()) return child;
  }
  return null;
}
```

Full version (skip-loop, React re-apply via observer, toggle-off behavior) is in
`references/code-patterns.md`. Toggle-off does **not** restore original text on screen;
turning the extension off stops the scanner and leaves replaced text in Persian until the
next page load. If the user wants the original back, they reload.

## Storage schema (`chrome.storage.local`)

| Key | Type | Purpose |
|---|---|---|
| `enabled` | boolean | Global toggle, default `true`; watched via `chrome.storage.onChanged` |
| `unknown_queue` | string[] | Normalized keys with no dictionary entry, de-duplicated, capped (e.g. 500) |

Do not add new storage keys without updating this table and `references/architecture.md`.

## Self-check before delivering

- [ ] MV3 only; no `fetch` except `chrome.runtime.getURL`, no XHR/WebSocket/remote URL/CDN (rules 1–2)
- [ ] No `eval`; translated text set via `nodeValue`/`textContent`, never `innerHTML` with data (rule 3)
- [ ] TRANSLATE_REPLACE: text node swapped with Persian; misses untouched + queued (rule 4)
- [ ] NEVER_TOUCH: choice cards, sentence tiles, word banks, hint popups, audio transcripts, inputs untouched (rule 5)
- [ ] Element never destroyed/re-created; only the text node changes (rule 6)
- [ ] Replaced nodes carry class `duo-fa-replaced` with `dir="rtl"` (rule 7)
- [ ] Extension UI strings in Persian with `dir="rtl"` (rule 8)
- [ ] Flat normalized dictionary, en→fa, ar→fa-ready (rule 9)
- [ ] `MutationObserver` on `document.body` with `characterData`, skips `.duo-fa-replaced`, debounced (rule 10)
- [ ] Behavior gated on `enabled`; live updates via `chrome.storage.onChanged` (rule 11)
- [ ] Comments in English, UI strings and dictionary values in Persian (rule 12)

## Resources

### references/
- `conventions.md` — each rule in depth with rationale and anti-patterns
- `architecture.md` — file layout, manifest, module responsibilities, data flow, storage schema
- `code-patterns.md` — copy-ready module implementations (renderer, engine, classifier, popup, dictionary)
- `review-checklist.md` — violation checklist, grep patterns, common bugs and fixes

### scripts/
- `lint_rules.py` — static scan of the extension source for rule violations
- `normalize_dict.py` — normalize / validate / de-duplicate `dict-en-fa.json`

### assets/
- `manifest.template.json`, `selectors.template.json`, `dict-en-fa.template.json` — starting points to copy
