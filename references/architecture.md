# Architecture

## File layout

```
duo-farsi/
├── manifest.json                  # MV3 manifest, no host_permissions beyond injection
├── src/
│   ├── content/
│   │   ├── index.js               # entry: boot, storage sync, observer wiring
│   │   ├── engine.js              # scan loop + MutationObserver + debounce
│   │   ├── classifier.js          # decide translate / skip / queue
│   │   ├── renderer.js            # swap text node, mark duo-fa-replaced
│   │   ├── dictionary.js          # load + normalize + lookup + unknown queue
│   │   └── content.css            # .duo-fa-replaced styles
│   ├── popup/
│   │   ├── popup.html             # <html dir="rtl" lang="fa">
│   │   ├── popup.js
│   │   └── popup.css
│   ├── shared/
│   │   ├── normalize.js           # the ONE key normalizer (mirrored in scripts/)
│   │   └── storage.js             # enabled + unknown_queue helpers
│   └── assets/
│       └── selectors.json         # source of truth; mirrored into shared/selectors.js
├── dictionaries/
│   └── dict-en-fa.json            # flat, normalized keys (V1 en→fa, ar→fa-ready)
└── icons/
    ├── icon-16.png
    ├── icon-48.png
    └── icon-128.png
```

Content scripts are plain scripts loaded in order via `manifest.json` — no bundler required.
If a bundler is introduced, keep the module boundaries identical.

## Module responsibilities

| Module | Owns | Must NOT do |
|---|---|---|
| `index.js` | boot order, read `enabled`, start engine | translate anything itself |
| `engine.js` | `MutationObserver`, debounce, `scan(root)` | touch the dictionary directly |
| `classifier.js` | allow/deny decision, key extraction | create/destroy DOM nodes |
| `renderer.js` | swap the text node, mark `duo-fa-replaced`, set `dir`/`lang` | decide *what* is translatable |
| `dictionary.js` | load JSON, `normalizeKey`, lookup, `queueUnknown` | render, observe, or fetch remote |
| `shared/storage.js` | `enabled`, `unknown_queue` read/write + `onChanged` | hold other state |
| popup | Persian UI, toggle `enabled`, show queue size | inject into the page |

Dependency direction: `index → engine → classifier → dictionary → shared`.
`renderer` is a leaf called by `classifier`/`engine`. No cycles.

## Manifest (see `assets/manifest.template.json`)

Key points:
- `"manifest_version": 3`
- `content_scripts`: `matches: ["https://www.duolingo.com/*"]`, `js` in dependency order,
  `css: ["src/content/content.css"]`, `run_at: "document_idle"`
- `web_accessible_resources`: only if the content script loads `dictionaries/dict-en-fa.json`
  with `chrome.runtime.getURL`; prefer bundling it as a JS module to avoid this entirely.
- `permissions: ["storage"]` — nothing else.
- `host_permissions`: omit; `matches` in `content_scripts` is enough.
- CSP: `script-src 'self'`.

## Data flow

```
storage(enabled) ──► index.js ──► engine.start()
                                    │
      MutationObserver(mutations) ──┤ debounce, skip .duo-fa-replaced
                                    ▼
                             engine.scan(root)
                                    │
                    for each candidate element
                                    ▼
                    classifier.shouldTranslate(el) ── no ──► skip
                                    │ yes
                                    ▼
                    key = normalizeKey(text node value)
                                    ▼
                    dictionary.lookup(key) ── miss ──► queueUnknown(key); touch nothing
                                    │ hit
                                    ▼
                    renderer.replaceText(el, fa)
                                    ▼
                    text node.nodeValue = fa; class duo-fa-replaced; dir=rtl
```

`enabled === false` short-circuits at the top of `scan()` and stops the observer's work.
It does **not** restore original text (rule 11); the user reloads to see originals.

## Storage schema

| Key | Type | Default | Writer | Reader |
|---|---|---|---|---|
| `enabled` | boolean | `true` | popup | content script (`shared/storage.js`) |
| `unknown_queue` | string[] | `[]` | content script (dictionary miss) | popup (count), dev tooling |

Size discipline: cap `unknown_queue` at ~500 entries; drop oldest on overflow.
Never write per-element state to storage — use the `duo-fa-replaced` class and an in-memory
`WeakMap`/`Set` cache for lookups.

## Selectors file (`assets/selectors.template.json`)

```json
{
  "version": 1,
  "translate": ["[data-test='...']", ".some-chrome-label"],
  "neverTranslate": [
    "input", "textarea", "[contenteditable]",
    "[data-test*='challenge'] [data-test*='sentence']",
    "[data-test*='challenge-choice']",
    "[data-test*='hint']", "[data-test*='solution']",
    "[data-test*='word-bank']", "[data-test*='audio-transcript']",
    ".duo-fa-replaced"
  ],
  "exerciseRoots": ["[data-test*='challenge']", "[class*='Challenge']"]
}
```

Rules:
- Selectors are data, not code — keep them in `selectors.json`, never hardcode a long list
  inside `classifier.js`. Content scripts cannot `import` JSON synchronously, so
  `selectors.json` is mirrored into `src/content/shared/selectors.js`
  (`const SELECTORS = {...}`) at build time, or written directly as that JS constant.
- Duolingo ships hashed class names; prefer stable `[data-test*="..."]` attributes and treat
  class-based selectors as best-effort with a fallback.
- Bump `version` when the shape changes.

## Performance notes

- Debounce 120–250 ms; batch DOM reads before writes.
- Keep a `WeakSet`/`Map` of already-classified elements to avoid re-classifying on every
  mutation.
- Skip mutations whose target is inside `.duo-fa-replaced` (rule 10) to avoid feedback
  loops.
- The dictionary is small; load it once into a `Map` and never re-read it per element.
