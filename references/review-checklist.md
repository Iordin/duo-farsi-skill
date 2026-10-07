# Review Checklist

Use this when reviewing, debugging, or auditing `duo-farsi` code.
Automated part first: `python3 scripts/lint_rules.py <project-root>`, then walk the manual list.

## 1. Automated scan

```bash
python3 scripts/lint_rules.py path/to/duo-farsi
python3 scripts/normalize_dict.py --check path/to/duo-farsi/dictionaries/dict-en-fa.json
```

Exit code `0` = no violations. Anything reported is a blocker unless explicitly justified.

## 2. Grep patterns (manual backup)

```bash
# Rules 1-2 — network + dangerous sinks
grep -RnE "fetch\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon|https?://" --include=*.js --include=*.json --include=*.html .
grep -RnE "\beval\(|new Function\(|innerHTML|outerHTML|insertAdjacentHTML|document\.write" --include=*.js .
# Rule 6 — element must not be destroyed
grep -RnE "\.remove\(\)|replaceChild|\.outerHTML\s*=|replaceWith" --include=*.js src/content/
# Rule 4 — text node swap (the positive signal)
grep -Rn "\.nodeValue\s*=" --include=*.js .
# Rule 5 — protected elements
grep -Rn "input\|textarea\|contenteditable\|word-bank\|challenge-choice" --include=*.js src/content/
# Rule 10 — observer options
grep -Rn "characterData" --include=*.js .
```

## 3. Manual checklist

**Rules 1–2 — offline + safe DOM**
- [ ] No host permission beyond what `content_scripts.matches` needs.
- [ ] Icons, fonts, CSS, and the dictionary are all packaged locally.
- [ ] `fetch` only ever takes `chrome.runtime.getURL(...)` or a local constant.
- [ ] Translated text reaches the DOM via `nodeValue`/`textContent`.
- [ ] No `innerHTML`/`insertAdjacentHTML`/`outerHTML` with data (only `= ''` is fine).
- [ ] No `eval`, `new Function`, `setTimeout` with a string argument.

**Rule 3 — TRANSLATE_REPLACE**
- [ ] Translation is written to the **text node** (`node.nodeValue = fa`), not an appended span.
- [ ] Miss leaves the element untouched and queues the normalized key.
- [ ] No placeholder text, no English echo on a miss.

**Rule 4 — NEVER_TOUCH**
- [ ] `input`, `textarea`, `[contenteditable]` skipped before anything else.
- [ ] Choice cards, sentence tiles, word banks, hint popups, audio transcripts skipped.
- [ ] The deny list comes from `selectors.json`, not from ad-hoc string matching.

**Rule 5 — preserve the element**
- [ ] No `el.remove()`, `replaceChild`, `el.replaceWith(...)`, `el.outerHTML = ...`.
- [ ] Only the text node's `nodeValue` changes.
- [ ] React re-render reverting text is expected; the observer re-applies it.

**Rule 6 — marking**
- [ ] Replaced elements get class `duo-fa-replaced`.
- [ ] `el.dir = 'rtl'` and `el.lang = 'fa'` set on the element.
- [ ] CSS does not aggressively override Duolingo's layout.

**Rule 7 — Persian UI**
- [ ] `popup.html` / options page have `dir="rtl" lang="fa"`.
- [ ] Every user-visible extension string is Persian.

**Rule 8 — dictionary**
- [ ] Flat object, no nesting.
- [ ] Keys normalized by the shared `normalizeKey` (build script and runtime identical).
- [ ] V1 en→fa; structure ready for ar→fa (no hardcoded source language in the loader).

**Rule 9 — observer**
- [ ] `MutationObserver` on `document.body` with `childList` + `characterData` + `subtree`.
- [ ] Mutations debounced; scan is batched.
- [ ] Mutations whose target is inside `.duo-fa-replaced` are ignored (no feedback loop).
- [ ] Observer disconnected on teardown.

**Rule 10 — toggle**
- [ ] `enabled` read from `chrome.storage.local` at boot.
- [ ] `chrome.storage.onChanged` updates `state.enabled` live.
- [ ] Off → stop scanning; replaced text stays Persian until reload (no restoration logic).
- [ ] On → re-scan immediately.

**Rule 11 — languages**
- [ ] Comments/logs in English.
- [ ] UI strings and dictionary values in Persian.

## 4. Common bugs and fixes

| Symptom | Cause | Fix |
|---|---|---|
| Text flickers / CPU spins | Observer reacting to its own `nodeValue` write | Skip mutations whose target is inside `.duo-fa-replaced`; debounce 150 ms |
| Translation disappears after a second | React reverted the text node | `characterData: true` on the observer; the scan re-applies it |
| Choice card got translated | Deny list evaluated after the lookup | Move `isProtected()` to the first line of `classify()` |
| Persian text shifts the English line | RTL text inside an LTR parent | `direction: rtl` + `unicode-bidi: isolate` on the element |
| Toggle does nothing until reload | Flag cached in a module variable only | Add `chrome.storage.onChanged` listener |
| "Cannot read nodeValue of null" | Element has no direct text node (icon-only, or text in a nested span) | `firstTextNode()` walks `childNodes`; skip elements with no text node |
| Dictionary hit rate looks low | Keys not normalized identically in build and runtime | Run `normalize_dict.py --write`; reuse `shared/normalize.js` verbatim |
| Popup shows English | Strings hardcoded in HTML/JS in English | Move to Persian constants, set with `textContent`, `dir="rtl"` |
| Element destroyed, React crashes | `el.remove()` or `replaceWith` used | Only `node.nodeValue = fa`; never destroy the element |

## 5. Review report format

When asked to review, answer with:

```
## Verdict
PASS | FAIL (n violations)

## Violations
- [rule #] file:line — what is wrong → required fix

## Notes
Non-blocking observations (performance, maintainability).
```

Be specific: always cite `file:line` and the rule number. Never approve code that
violates rules 1–5.
