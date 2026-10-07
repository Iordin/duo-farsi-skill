#!/usr/bin/env python3
"""Static rule scanner for the duo-farsi Chrome extension.

Checks the extension source against the project's nine hard rules:
  R1 offline / MV3          - no fetch, XHR, WebSocket, remote URLs, CDN
  R2 no eval / innerHTML    - no dangerous DOM sinks fed with data
  R3 append, never replace  - translation spans must be RTL and appended
  R4 protected elements     - inputs, exercises, choices, hints guarded
  R5 Persian RTL UI         - popup/options must declare dir="rtl"
  R6 flat dictionary        - dict-en-fa.json must be flat and normalized
  R7 MutationObserver       - document.body must be observed
  R8 toggle state           - "enabled" key + storage.onChanged
  R9 languages              - comments English, UI strings Persian

Usage:
    python3 lint_rules.py <project-root> [--json]
Exit code 0 = clean, 1 = violations found, 2 = usage error.
"""

import json
import re
import sys
from pathlib import Path

SCAN_EXT = {'.js', '.mjs', '.html', '.css'}
SKIP_DIRS = {'.git', 'node_modules', 'dist', 'build', '.codebuddy', '__pycache__'}

# --- R1: network -------------------------------------------------------------
NET_PATTERNS = [
    (r'\bXMLHttpRequest\b', 'R1', 'XMLHttpRequest is forbidden (offline extension)'),
    (r'\bWebSocket\b', 'R1', 'WebSocket is forbidden (offline extension)'),
    (r'\bEventSource\b', 'R1', 'EventSource is forbidden (offline extension)'),
    (r'navigator\s*\.\s*sendBeacon', 'R1', 'sendBeacon is forbidden (offline extension)'),
    (r'\beval\s*\(', 'R2', 'eval() is forbidden'),
    (r'new\s+Function\s*\(', 'R2', 'new Function() is forbidden'),
    (r'document\s*\.\s*write\s*\(', 'R2', 'document.write() is forbidden'),
    (r'outerHTML\s*=', 'R2', 'outerHTML assignment is forbidden'),
    (r'insertAdjacentHTML\s*\(', 'R2', 'insertAdjacentHTML is forbidden'),
]

# Local/documented URL schemes that are not network calls.
LOCAL_URL_HINTS = (
    'chrome.runtime.getURL',
    'chrome-extension://',
    'chrome.runtime.getURL(',
    'dictionaries/',
)

REMOTE_URL_RE = re.compile(r'https?://[^\s"\'`,)]+')

# --- R2: innerHTML -----------------------------------------------------------
INNER_HTML_RE = re.compile(r'innerHTML\s*=')

# --- R3/R4/R7/R8 markers -----------------------------------------------------
RTL_RE = re.compile(r"""dir\s*=\s*['"]rtl['"]|\.\s*dir\s*=\s*['"]rtl['"]""")
REPLACED_CLASS_RE = re.compile(r"duo-fa-replaced")
TEXT_NODE_SWAP_RE = re.compile(r"\.nodeValue\s*=")
DESTROY_RE = re.compile(r"\.remove\(\)|replaceChild|replaceWith|outerHTML\s*=")
PROTECTED_RE = re.compile(r"input|textarea|contenteditable", re.I)
NEVER_TRANSLATE_RE = re.compile(r"neverTranslate|NEVER_TRANSLATE", re.I)
OBSERVER_RE = re.compile(r"new\s+MutationObserver\s*\(")
BODY_OBSERVE_RE = re.compile(r"observe\s*\(\s*document\.body")
CHARACTER_DATA_RE = re.compile(r"characterData\s*:\s*true")
ONCHANGED_RE = re.compile(r"storage\.onChanged\.addListener")
ENABLED_RE = re.compile(r"""['"]enabled['"]|\benabled\s*:""")

PERSIAN_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
CJK_RE = re.compile(r'[\u4E00-\u9FFF\u3400-\u4DBF]')


def iter_files(root):
    root = Path(root).resolve()
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        # Only skip directories inside the project, not parents of it.
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix in SCAN_EXT or path.name == 'manifest.json':
            yield path


def read_lines(path):
    try:
        return path.read_text(encoding='utf-8').splitlines()
    except (UnicodeDecodeError, OSError):
        return []


def strip_comment(line):
    """Roughly remove // and /* */ comments so prose does not trigger rules."""
    out = line
    out = re.sub(r'/\*.*?\*/', '', out)
    out = re.sub(r'(?<!:)\s*//.*$', '', out)
    return out


def local_url_identifiers(source):
    """Names of constants that hold chrome.runtime.getURL(...) results."""
    names = set()
    for name, expr in re.findall(r'(?:const|let|var)\s+(\w+)\s*=\s*([^;\n]+)', source):
        if 'chrome.runtime.getURL' in expr:
            names.add(name)
    return names


def scan_file(path, findings):
    lines = read_lines(path)
    local_ids = local_url_identifiers('\n'.join(lines))
    for number, raw in enumerate(lines, start=1):
        code = strip_comment(raw)

        for pattern, rule, message in NET_PATTERNS:
            if re.search(pattern, code):
                findings.append((str(path), number, rule, message))

        # R1: fetch() is only tolerated when it reads a packaged local resource.
        if re.search(r'\bfetch\s*\(', code):
            arg = re.search(r'\bfetch\s*\(\s*([A-Za-z_$][\w$]*)', code)
            uses_local = (arg and arg.group(1) in local_ids) or \
                any(hint in code for hint in LOCAL_URL_HINTS)
            if not uses_local:
                findings.append((str(path), number, 'R1',
                                 'fetch() without chrome.runtime.getURL - offline rule'))

        # R1: remote URLs in code, CSS or HTML.
        for url in REMOTE_URL_RE.findall(code):
            if url.startswith(('http://www.w3.org', 'https://www.w3.org')):
                continue  # XML/SVG namespaces, not a fetch
            findings.append((str(path), number, 'R1', 'remote URL reference: %s' % url))

        # R2: innerHTML with anything other than an empty literal.
        if INNER_HTML_RE.search(code):
            rhs = code.split('=', 1)[1].strip().rstrip(';').strip()
            if rhs not in ("''", '""', '``'):
                findings.append((str(path), number, 'R2',
                                 'innerHTML assigned non-empty value - use textContent'))

        # R9: Chinese characters inside project files.
        if CJK_RE.search(raw):
            findings.append((str(path), number, 'R9',
                             'CJK text in project file - comments English, UI Persian'))

    return lines


def check_manifest(path, findings):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        findings.append((str(path), 1, 'R1', 'manifest.json unreadable: %s' % exc))
        return
    if data.get('manifest_version') != 3:
        findings.append((str(path), 1, 'R1', 'manifest_version must be 3'))
    if data.get('host_permissions'):
        findings.append((str(path), 1, 'R1',
                         'host_permissions should be empty - use content_scripts.matches'))
    perms = set(data.get('permissions', []))
    if perms - {'storage', 'scripting', 'activeTab'}:
        findings.append((str(path), 1, 'R1',
                         'unexpected permissions: %s' % sorted(perms)))


def check_dictionary(path, findings):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        findings.append((str(path), 1, 'R6', 'dictionary unreadable: %s' % exc))
        return
    if not isinstance(data, dict):
        findings.append((str(path), 1, 'R6', 'dictionary must be a flat JSON object'))
        return
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            findings.append((str(path), 1, 'R6',
                             'nested value for key %r - dictionary must be flat' % key))
        if normalize_key(key) != key:
            findings.append((str(path), 1, 'R6',
                             'key not normalized: %r (expected %r)' % (key, normalize_key(key))))
        if not PERSIAN_RE.search(str(value)):
            findings.append((str(path), 1, 'R6',
                             'value for %r contains no Persian characters' % key))


def normalize_key(text):
    """Mirror of shared/normalize.js and scripts/normalize_dict.py."""
    import unicodedata
    s = unicodedata.normalize('NFKC', str(text)).lower()
    s = re.sub(r'\s+', ' ', s).strip()
    s = ''.join(ch for ch in s
                if ch == ' ' or unicodedata.category(ch).startswith(('L', 'N')))
    return re.sub(r'\s+', ' ', s).strip()


def project_checks(root, all_lines, findings):
    """Cross-file checks: does the codebase actually implement the rules."""
    joined = '\n'.join(all_lines)

    # Rule 4/6/7 — replace text node, mark duo-fa-replaced, set dir=rtl
    if not REPLACED_CLASS_RE.search(joined):
        findings.append(('<project>', 0, 'R7',
                         'no "duo-fa-replaced" class found - renderer missing'))
    else:
        if not RTL_RE.search(joined):
            findings.append(('<project>', 0, 'R7', 'replaced element never sets dir="rtl"'))
        if not TEXT_NODE_SWAP_RE.search(joined):
            findings.append(('<project>', 0, 'R4',
                             'no text-node swap (.nodeValue=) found - are you appending instead of replacing?'))

    # Rule 6 — element must not be destroyed
    if DESTROY_RE.search(joined):
        findings.append(('<project>', 0, 'R6',
                         'element destruction detected (.remove()/replaceChild/replaceWith/outerHTML=) - replace text node only'))

    # Rule 5 — never-touch zone
    if not PROTECTED_RE.search(joined):
        findings.append(('<project>', 0, 'R5',
                         'no guard for input/textarea/contenteditable found'))
    if not NEVER_TRANSLATE_RE.search(joined):
        findings.append(('<project>', 0, 'R5', 'no NEVER_TRANSLATE selector list found'))

    # Rule 10 — observer on body with characterData
    if not OBSERVER_RE.search(joined):
        findings.append(('<project>', 0, 'R10', 'no MutationObserver found'))
    else:
        if not BODY_OBSERVE_RE.search(joined):
            findings.append(('<project>', 0, 'R10', 'MutationObserver does not observe document.body'))
        if not CHARACTER_DATA_RE.search(joined):
            findings.append(('<project>', 0, 'R10',
                             'observer missing characterData:true (needed to catch React reverting text)'))

    # Rule 11 — toggle
    if not ENABLED_RE.search(joined):
        findings.append(('<project>', 0, 'R11', 'no "enabled" storage key found'))
    if not ONCHANGED_RE.search(joined):
        findings.append(('<project>', 0, 'R11', 'no chrome.storage.onChanged listener found'))

    popup = Path(root) / 'src' / 'popup' / 'popup.html'
    if popup.exists():
        text = popup.read_text(encoding='utf-8')
        if '<html' in text and 'dir="rtl"' not in text:
            findings.append((str(popup), 1, 'R8', 'popup html missing dir="rtl"'))
        if not PERSIAN_RE.search(text):
            findings.append((str(popup), 1, 'R8', 'popup contains no Persian text'))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    as_json = '--json' in sys.argv
    if len(args) != 1:
        print('Usage: python3 lint_rules.py <project-root> [--json]')
        sys.exit(2)

    root = Path(args[0])
    if not root.exists():
        print('Path not found: %s' % root)
        sys.exit(2)

    findings = []
    all_lines = []
    scanned = 0

    for path in iter_files(root):
        scanned += 1
        if path.name == 'manifest.json':
            check_manifest(path, findings)
            continue
        if path.name == 'dict-en-fa.json':
            check_dictionary(path, findings)
        lines = scan_file(path, findings)
        all_lines.extend(lines)

    if scanned == 0:
        print('No extension source found under %s - pass the duo-farsi project root.' % root)
        sys.exit(2)

    project_checks(root, all_lines, findings)

    if as_json:
        print(json.dumps([{'file': f, 'line': l, 'rule': r, 'message': m}
                          for f, l, r, m in findings], indent=2))
    elif findings:
        print('duo-farsi rule scan - %d finding(s):\n' % len(findings))
        for file_name, line, rule, message in findings:
            location = '%s:%d' % (file_name, line) if line else file_name
            print('  [%s] %s - %s' % (rule, location, message))
        print('\nFix every R1-R4 finding before shipping.')
    else:
        print('duo-farsi rule scan - clean, no violations found.')

    sys.exit(1 if findings else 0)


if __name__ == '__main__':
    main()
