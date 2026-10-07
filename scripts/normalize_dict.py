#!/usr/bin/env python3
"""Normalize and validate dict-en-fa.json for the duo-farsi extension.

Implements exactly the same normalization as src/shared/normalize.js:
  1. NFKC normalize
  2. lowercase
  3. collapse whitespace
  4. trim
  5. strip punctuation (keep letters, numbers and single spaces)
  6. collapse + trim again

Usage:
    python3 normalize_dict.py dict-en-fa.json                 # report only
    python3 normalize_dict.py --check dict-en-fa.json         # fail on issues (exit 1)
    python3 normalize_dict.py --write dict-en-fa.json         # rewrite normalized + sorted
    python3 normalize_dict.py --stubs unknown_queue.json      # print empty entries to fill

Exit code 0 = clean, 1 = issues found (only with --check), 2 = usage error.
"""

import json
import re
import sys
import unicodedata
from collections import OrderedDict
from pathlib import Path

PERSIAN_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')


def normalize_key(text):
    """Mirror of shared/normalize.js - keep the two implementations identical."""
    s = unicodedata.normalize('NFKC', str(text)).lower()
    s = re.sub(r'\s+', ' ', s).strip()
    s = ''.join(ch for ch in s
                if ch == ' ' or unicodedata.category(ch).startswith(('L', 'N')))
    return re.sub(r'\s+', ' ', s).strip()


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        print('Cannot read %s: %s' % (path, exc))
        sys.exit(2)
    if not isinstance(data, dict):
        print('Dictionary must be a flat JSON object, got %s' % type(data).__name__)
        sys.exit(2)
    return data


def audit(data):
    """Return (issues, normalized_mapping, collisions)."""
    issues = []
    seen = {}
    collisions = []

    for key, value in data.items():
        norm = normalize_key(key)
        if not norm:
            issues.append('empty normalized key from %r - entry ignored at runtime' % key)
            continue
        if norm != key:
            issues.append('key not normalized: %r -> %r' % (key, norm))
        if not isinstance(value, str):
            issues.append('value for %r is %s, must be a Persian string'
                          % (key, type(value).__name__))
        elif not value.strip():
            issues.append('empty value for %r' % key)
        elif not PERSIAN_RE.search(value):
            issues.append('value for %r contains no Persian characters' % key)
        if norm in seen:
            collisions.append('collision: %r and %r both normalize to %r'
                              % (seen[norm], key, norm))
        else:
            seen[norm] = key

    return issues + collisions, seen, collisions


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)

    path = Path(args[0])
    data = load(path)
    issues, mapping, _ = audit(data)

    if '--stubs' in flags:
        # Input is an unknown_queue dump: emit empty entries ready to translate.
        keys = data if isinstance(data, list) else list(data.keys())
        stubs = OrderedDict((normalize_key(k), '') for k in keys if normalize_key(k))
        print(json.dumps(stubs, ensure_ascii=False, indent=2))
        sys.exit(0)

    if '--write' in flags:
        normalized = OrderedDict()
        for key in sorted(data, key=normalize_key):
            norm = normalize_key(key)
            if norm:
                normalized[norm] = data[key]
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + '\n',
                        encoding='utf-8')
        removed = len(data) - len(normalized)
        print('Wrote %d normalized entries to %s (%d collapsed/removed).'
              % (len(normalized), path, removed))
        sys.exit(0)

    print('Dictionary: %s' % path)
    print('Entries: %d, unique normalized keys: %d' % (len(data), len(mapping)))
    if issues:
        print('\nIssues (%d):' % len(issues))
        for issue in issues:
            print('  - %s' % issue)
        print('\nRun with --write to normalize and sort in place.')
    else:
        print('No issues found - dictionary is normalized.')

    sys.exit(1 if (issues and '--check' in flags) else 0)


if __name__ == '__main__':
    main()
