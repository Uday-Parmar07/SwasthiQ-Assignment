"""Conversation-scoped authority. Model arguments never establish caller identity.

The assignment supplies synthetic identities, not authentication. We require a
caller-provided phone/name match, and check proxy relationships in clinic.json.
An actual deployment would need authenticated callers in addition to this policy.
"""
from __future__ import annotations

import re
from app.database import ClinicState
from app.agent.date_resolver import resolve_date_from_turns, resolve_time_from_turns

MUTATIONS = {"book_appointment", "reschedule_appointment", "cancel_appointment"}
CHILD = re.compile(r"\b(bete|beta|beti|child|son|daughter)\b", re.I)
PROXY = re.compile(r"\b(padosi|neighbou?r|colleague|coworker|co-worker|friend|dost|wife|husband|on behalf)\b", re.I)


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def phones(text: str) -> set[str]:
    return {
        re.sub(r"\D", "", m.group())[-10:]
        for m in re.finditer(r"(?<!\d)(?:(?:\+?91|0)[ -]?)?[6-9](?:[ -]?\d){9}(?!\d)", text)
    }


def mentioned(patient: dict, text: str, first_only: bool = False) -> bool:
    tokens = words(patient["name"])
    haystack = words(text)
    needle = tokens[:1] if first_only else tokens
    return any(haystack[i:i + len(needle)] == needle for i in range(len(haystack)))


class Policy:
    def __init__(self, state: ClinicState):
        self.state = state
        self.turns: list[str] = []
        self.looked_up: set[str] = set()
        self.known_appointments: set[str] = set()
        self.slots: set[tuple[str, str, str]] = set()
        self.stopped = False
        self.final_turn = False
        self.today: str | None = None

    def intent(self) -> str | None:
        text = ' '.join(self.turns).casefold()
        actions = list(re.finditer(r'\b(cancel(?:lation)?|reschedule|move|shift|badal)\b', text))
        if actions:
            return 'cancel_appointment' if actions[-1][1].startswith('cancel') else 'reschedule_appointment'
        if re.search(r'appointment\s+hai\b', text) and re.search(r'\b(use|karwana|change)\b', text):
            return 'reschedule_appointment'
        if re.search(r'\b(appointment|book|milna|dikhana|aa sakta|chahiye|saath)\b', text):
            return 'book_appointment'
        return None

    def requested_doctor(self) -> str | None:
        text = ' '.join(self.turns)
        matches = [(m.start(), doctor['id']) for doctor in self.state.doctors
                   for m in re.finditer(r'\b' + re.escape(doctor['name'].split()[-1]) + r'\b', text, re.I)]
        return max(matches)[1] if matches else None

    def identities(self) -> tuple[str | None, str | None, str | None]:
        text = " ".join(self.turns)
        numbers = phones(text)
        patients = self.state.patients
        candidates = [p for p in patients if p["phone"] in numbers]
        named = [p for p in candidates if mentioned(p, text)]
        # A named guardian identifies the caller; child first names identify
        # the target independently. There are no fixture-specific names here.
        if CHILD.search(text):
            guardians = [p for p in named if p.get("guardian_of")]
            if len(guardians) != 1:
                return None, None, "ambiguous_patient" if candidates else "not_authorised"
            actor = guardians[0]
            children = [p for p in patients if p["id"] in actor["guardian_of"]]
            targets = [p for p in children if mentioned(p, text, first_only=True)]
            if len(targets) != 1:
                return actor["id"], None, "ambiguous_patient"
            return actor["id"], targets[0]["id"], None

        if len(named) == 1:
            actor = named[0]
        elif len(candidates) == 1 and not PROXY.search(text):
            actor = candidates[0]
        else:
            return None, None, "ambiguous_patient" if candidates or numbers else None

        other_names = [p for p in patients if p["id"] != actor["id"] and mentioned(p, text)]
        if other_names or PROXY.search(text):
            if len(other_names) == 1 and other_names[0]["id"] in actor.get("guardian_of", []):
                return actor["id"], other_names[0]["id"], None
            return actor["id"], None, "not_authorised"
        return actor["id"], actor["id"], None

    def authorize(self, name: str, arguments: dict) -> str | None:
        if self.stopped:
            return "Conversation handed off; no further tools may execute."
        if name not in MUTATIONS:
            return None
        if not self.final_turn:
            return "Collect the remaining caller turns before committing a mutation."
        intent = self.intent()
        if name != intent:
            return f"Requested tool does not match caller intent ({intent or 'unresolved'})."
        text = ' '.join(self.turns).casefold()
        if re.search(r'baad mein call|call (?:you )?back|never mind|appointment nahi chahiye', text):
            return "Caller ended or withdrew the request; do not mutate appointments."
        actor, target, reason = self.identities()
        if reason or not actor or not target:
            return f"Caller/patient not verified: {reason or 'provide caller name and phone'}."
        if arguments.get("patient_id") != target:
            return "Requested patient differs from the verified intended patient."
        if actor not in self.looked_up or target not in self.looked_up:
            return "lookup_patient must return both the caller and intended patient before mutation."
        if name in {"cancel_appointment", "reschedule_appointment"}:
            if arguments.get("appointment_id") not in self.known_appointments:
                return "Use an authorized appointment ID returned by lookup_patient."
        if name == "book_appointment":
            doctor = self.requested_doctor()
            if doctor and arguments.get('doctor_id') != doctor:
                return "Use the caller's requested doctor, not a substitute."
            slot = (arguments.get("doctor_id"), arguments.get("date"), arguments.get("start"))
            if slot not in self.slots:
                return "Use an available slot returned by search_slots before booking."
        if self.today and name in {'book_appointment', 'reschedule_appointment'}:
            requested_date = resolve_date_from_turns(self.turns, self.today)
            requested_time = resolve_time_from_turns(self.turns)
            date_arg = 'date' if name == 'book_appointment' else 'new_date'
            time_arg = 'start' if name == 'book_appointment' else 'new_start'
            if requested_date and arguments.get(date_arg) != requested_date:
                return "Use the caller's latest requested date; do not silently substitute another date."
            if requested_time and arguments.get(time_arg) != requested_time:
                return "Use the caller's latest requested time; do not silently substitute another time."
        if name == "reschedule_appointment":
            appointments = self.state.get_appointments_for_patient(target)
            ap = next((a for a in appointments if a["id"] == arguments.get("appointment_id")), None)
            doctor = self.requested_doctor()
            if ap and doctor and ap['doctor_id'] != doctor:
                return "Selected appointment does not match the requested doctor."
            slot = (ap["doctor_id"] if ap else None, arguments.get("new_date"), arguments.get("new_start"))
            if slot not in self.slots:
                return "Use an available destination returned by search_slots before rescheduling."
        return None

    def observe(self, name: str, result: dict) -> dict:
        if "error" in result:
            return result
        if name == "lookup_patient":
            candidates = result.get("candidates", [])
            self.looked_up.update(p["id"] for p in candidates)
            actor, target, reason = self.identities()
            # Appointment details are disclosed only for a resolved, authorized
            # target, after the caller has also been returned by a lookup.
            for p in candidates:
                if not reason and actor in self.looked_up and p["id"] == target:
                    p["appointments"] = self.state.get_appointments_for_patient(p["id"])
                    self.known_appointments.update(a["id"] for a in p["appointments"])
        elif name == "search_slots":
            self.slots.update((result["doctor_id"], result["date"], s) for s in result.get("slots", []))
        elif name == "escalate_to_human" and result.get("escalated"):
            self.stopped = True
        return result
