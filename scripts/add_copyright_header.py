#!/usr/bin/env python3
# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Pre-commit hook: ensure every Python source file carries an SPDX Apache-2.0 header.

Files that already contain an ``SPDX-License-Identifier`` marker near the top
(including the full Apache license block) are left untouched. Any file missing
it gets a concise two-line header inserted (after a shebang, if present). The
hook exits non-zero when it modifies a file so the change is re-staged and
reviewed, matching standard pre-commit behaviour.
"""

from __future__ import annotations

import sys

HEADER_LINES = [
    "# Copyright (c) 2026, Salesforce, Inc.",
    "# SPDX-License-Identifier: Apache-2.0",
]
MARKER = "SPDX-License-Identifier"
HEAD_SCAN_LINES = 15


def has_header(text: str) -> bool:
    head = "\n".join(text.splitlines()[:HEAD_SCAN_LINES])
    return MARKER in head


def insert_header(path: str) -> bool:
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    if has_header(content):
        return False

    lines = content.splitlines(keepends=True)
    insert_at = 0
    # Preserve a shebang line if present.
    if lines and lines[0].startswith("#!"):
        insert_at = 1

    header = "\n".join(HEADER_LINES) + "\n"
    # Keep a blank line between the header and following code.
    if insert_at < len(lines) and lines[insert_at].strip():
        header += "\n"

    new_lines = lines[:insert_at] + [header] + lines[insert_at:]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(new_lines))
    return True


def main(argv: list[str]) -> int:
    changed = []
    for path in argv:
        if not path.endswith(".py"):
            continue
        if insert_header(path):
            changed.append(path)
    for p in changed:
        print(f"Added copyright header to {p}")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
