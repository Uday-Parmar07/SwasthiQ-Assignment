"""Conservative date/time hints, anchored only to the request's today value."""
from __future__ import annotations
import calendar
import re
from datetime import date, datetime, timedelta
from typing import Optional

DAYS = {
    'somwar': 0, 'monday': 0, 'mangalwar': 1, 'tuesday': 1,
    'budhwar': 2, 'wednesday': 2, 'guruwar': 3, 'veervar': 3, 'thursday': 3,
    'shukrawar': 4, 'shukravar': 4, 'friday': 4,
    'shanivaar': 5, 'shanivar': 5, 'saturday': 5, 'ravivar': 6, 'sunday': 6,
}
NUMBERS = {'ek': 1, 'do': 2, 'teen': 3, 'char': 4, 'paanch': 5, 'cheh': 6,
           'saat': 7, 'aath': 8, 'nau': 9, 'das': 10, 'gyarah': 11, 'barah': 12}
MONTHS = {n.lower(): i for i, n in enumerate(calendar.month_name) if n}
MONTHS.update({n.lower(): i for i, n in enumerate(calendar.month_abbr) if n})
CORRECTION = r'\b(?:nahi(?:[\s,]+nahi)?|no[, ]+actually|actually|instead)\b'


def resolve_date(text: str, today: str) -> Optional[str]:
    base = date.fromisoformat(today)
    text = re.split(CORRECTION, text.casefold())[-1]
    hits = []
    for m in re.finditer(r'\b\d{4}-\d{2}-\d{2}\b', text):
        try: hits.append((m.start(), date.fromisoformat(m.group())))
        except ValueError: return None
    explicit = r'\b(\d{1,2})(?:st|nd|rd|th)?\s*(' + '|'.join(MONTHS) + r'|tareekh|taarikh|tarikh|ko\b)(?:\s+(\d{4}))?'
    for m in re.finditer(explicit, text):
        day, label, year = int(m[1]), m[2], m[3]
        month = MONTHS.get(label, base.month)
        try:
            candidate = date(int(year) if year else base.year, month, day)
            if candidate < base and label not in MONTHS:
                month = base.month % 12 + 1
                candidate = date(base.year + (base.month == 12), month, day)
            hits.append((m.start(), candidate))
        except ValueError:
            return None
    relative = {'day after tomorrow': 2, 'parso': 2, 'tarson': 3,
                'tomorrow': 1, 'kal': 1, 'today': 0, 'aaj': 0}
    pattern = r'\b(' + '|'.join(relative) + '|' + '|'.join(DAYS) + r')\b'
    for m in re.finditer(pattern, text):
        word = m.group()
        if word in relative:
            delta = relative[word]
        else:
            delta = (DAYS[word] - base.weekday()) % 7 or 7
        hits.append((m.start(), base + timedelta(days=delta)))
    return max(hits, key=lambda item: item[0])[1].isoformat() if hits else None


def resolve_time(text: str) -> Optional[str]:
    text = re.split(CORRECTION, text.casefold())[-1]
    numeral = r'(?:\d{1,2}|' + '|'.join(NUMBERS) + ')'
    pattern = (r'\b(?:(sawa|sadhe|saadhe|paune)\s+(' + numeral + r')'
               r'|(\d{1,2})[:.](\d{2})(?:\s*(am|pm))?'
               r'|(' + numeral + r')\s*(baje|am|pm)'
               r'|(?:subah|shaam|raat|morning|evening|afternoon|at)\s+(' + numeral + r'))\b')
    matches = list(re.finditer(pattern, text))
    if not matches:
        return None
    m = matches[-1]
    value = m[2] or m[3] or m[6] or m[8]
    hour = NUMBERS.get(value, int(value) if value.isdigit() else -1)
    minute = int(m[4] or 0)
    if m[1] in ('sadhe', 'saadhe'): minute = 30
    elif m[1] == 'sawa': minute = 15
    elif m[1] == 'paune': hour, minute = hour - 1, 45
    session = (m[5] or m[7] or '')
    prefix = text[max(0, m.start() - 30):m.end()]
    if session == 'pm' or re.search(r'\b(shaam|raat|evening|afternoon|dopahar)\b', prefix):
        if hour < 12: hour += 12
    elif session == 'am' or re.search(r'\b(subah|morning)\b', prefix):
        if hour == 12: hour = 0
    elif 1 <= hour <= 5:
        hour += 12
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return f'{hour:02d}:{minute:02d}'


def resolve_date_from_turns(turns: list[str], today: str) -> Optional[str]:
    result = None
    for turn in turns:
        result = resolve_date(turn, today) or result
    return result


def resolve_time_from_turns(turns: list[str]) -> Optional[str]:
    result = None
    for turn in turns:
        result = resolve_time(turn) or result
    return result
