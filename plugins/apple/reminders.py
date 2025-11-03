from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ReminderItem:
    reminder_id: str
    title: str
    list_name: str
    due: Optional[str]


def fetch_reminders_from_list(list_name: str) -> List[ReminderItem]:
    script = f'''
    set _sep to "\t"
    tell application "Reminders"
        if not (exists list "{list_name}") then return ""
        set theList to list "{list_name}"
        set theRems to reminders of theList whose completed is false
        repeat with r in theRems
            set rid to id of r
            set rtitle to name of r
            set rdue to due date of r
            if rdue is missing value then
                set rdueStr to ""
            else
                set rdueStr to (rdue as string)
            end if
            do shell script "printf '%s" & _sep & "%s" & _sep & "%s" & _sep & "%s\\n' " & quoted form of (rid as string) & " " & quoted form of (rtitle as string) & " " & quoted form of (name of theList as string) & " " & quoted form of rdueStr
        end repeat
    end tell
    '''
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    items: List[ReminderItem] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        rid, title, lst, due = parts
        due = due or None
        items.append(ReminderItem(reminder_id=rid, title=title, list_name=lst, due=due))
    return items


