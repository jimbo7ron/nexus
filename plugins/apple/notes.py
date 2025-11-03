from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List


@dataclass
class NoteItem:
    note_id: str
    title: str
    body: str
    folder: str


def fetch_notes_from_folder(folder_name: str) -> List[NoteItem]:
    script = f'''
    set _sep to "\t"
    tell application "Notes"
        if not (exists folder "{folder_name}") then return ""
        set theFolder to folder "{folder_name}"
        set theNotes to notes of theFolder
        repeat with n in theNotes
            set nid to id of n
            set ntitle to name of n
            set nbody to body of n
            do shell script "printf '%s" & _sep & "%s" & _sep & "%s" & _sep & "%s\\n' " & quoted form of (nid as string) & " " & quoted form of (ntitle as string) & " " & quoted form of (nbody as string) & " " & quoted form of (name of theFolder as string)
        end repeat
    end tell
    '''
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    items: List[NoteItem] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        nid, title, body, folder = parts
        items.append(NoteItem(note_id=nid, title=title, body=body, folder=folder))
    return items


