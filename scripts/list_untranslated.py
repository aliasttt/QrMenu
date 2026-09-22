"""Fail when a non-English gettext catalog can fall back to English."""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
TOKEN_RE = re.compile(r"%\([^)]+\)[a-zA-Z]")
QUESTION_MARK_ALLOWED = {"What data will be deleted"}


def quoted(line: str) -> str:
    return ast.literal_eval(line[line.index('"') :])


def value(lines: list[str], prefix: str) -> str | None:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            parts = [quoted(line)]
            for continuation in lines[index + 1 :]:
                if not continuation.startswith('"'):
                    break
                parts.append(ast.literal_eval(continuation))
            return "".join(parts)
    return None


def issues(path: Path) -> list[str]:
    problems: list[str] = []
    blocks = path.read_text(encoding="utf-8-sig").split("\n\n")
    for block in blocks:
        lines = block.splitlines()
        if not lines or any(line.startswith("#~") for line in lines):
            continue
        msgid = value(lines, "msgid ")
        if not msgid:
            continue
        if any("fuzzy" in line for line in lines if line.startswith("#,")):
            problems.append(f"fuzzy: {msgid!r}")
            continue
        is_plural = value(lines, "msgid_plural ") is not None
        if not is_plural:
            translations = [value(lines, "msgstr ")]
        else:
            translations = [
                value(lines, f"msgstr[{index}] ")
                for index in range(sum(line.startswith("msgstr[") for line in lines))
            ]
        for translation in translations:
            if not translation:
                problems.append(f"empty: {msgid!r}")
            elif "�" in translation or ("?" in translation and "?" not in msgid and msgid not in QUESTION_MARK_ALLOWED):
                problems.append(f"encoding: {msgid!r}")
            elif not is_plural and Counter(TOKEN_RE.findall(msgid)) != Counter(TOKEN_RE.findall(translation)):
                problems.append(f"tokens: {msgid!r}")
    return problems


def main() -> int:
    failed = False
    for path in sorted((BASE / "locale").glob("*/LC_MESSAGES/django.po")):
        if path.parts[-3] == "en":
            continue
        found = issues(path)
        print(f"{path.parts[-3]}: {'OK' if not found else f'{len(found)} issue(s)'}")
        for problem in found:
            print(f"  {problem}")
        failed |= bool(found)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
