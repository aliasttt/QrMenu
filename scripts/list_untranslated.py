"""List msgids from any .po that have empty msgstr (untranslated)."""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
po = BASE / "locale" / "de" / "LC_MESSAGES" / "django.po"
text = po.read_text(encoding="utf-8")
lines = text.split("\n")

i = 0
result = []
while i < len(lines):
    if lines[i].startswith("msgid \"") and not lines[i].startswith("msgid_plural"):
        m = re.match(r'^msgid "(.*)"$', lines[i])
        if not m:
            i += 1
            continue
        parts = [m.group(1)]
        k = i + 1
        while k < len(lines) and lines[k].startswith("\""):
            mm = re.match(r'^"(.*)"$', lines[k])
            if mm:
                parts.append(mm.group(1))
            k += 1
        msgid = "".join(parts)
        # skip empty header msgid
        if not msgid:
            i = k
            continue
        # check msgstr
        if k < len(lines) and lines[k].startswith("msgstr \""):
            msgstr_parts = []
            m2 = re.match(r'^msgstr "(.*)"$', lines[k])
            if m2:
                msgstr_parts.append(m2.group(1))
            j = k + 1
            while j < len(lines) and lines[j].startswith("\""):
                mm = re.match(r'^"(.*)"$', lines[j])
                if mm:
                    msgstr_parts.append(mm.group(1))
                j += 1
            msgstr = "".join(msgstr_parts)
            if not msgstr:
                # unescape msgid for display
                display = msgid.replace('\\"', '"').replace("\\n", "\\n").replace("\\\\", "\\")
                result.append(display)
            i = j
        else:
            i = k
    else:
        i += 1

for r in result:
    print(repr(r))
print("---")
print(f"TOTAL: {len(result)}")
