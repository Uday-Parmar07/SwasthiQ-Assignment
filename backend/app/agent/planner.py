"""Conservative deterministic completion of explicit scheduling requests.

Returns a proposal only when the caller's request and tool evidence suffice.
The same Policy checks apply to these proposals and to model-proposed actions.
Unrecognized language remains the model planner's responsibility.
"""
import re
from app.agent.date_resolver import DAYS, MONTHS, NUMBERS, resolve_date_from_turns, resolve_time_from_turns

# A bounded scheduling vocabulary keeps unrecognized clauses on the semantic
# model path. Merely finding a date/phone must not bypass an unfamiliar symptom.
SCHEDULING_WORDS = set('''
namaste hello hi please thanks thank you ji haan yes no nahi accha acha achha toh to
main mein me mera mere meri mujhe ka ki ke ko se saath paas liye par use unka uska
hai hain ho hoon hun tha thi the ab aaj kal parso tarson kar karo karna karwana
karwani karni dijiye do chahiye chahta chahti sakta sakti aa aana milna dikhana
bol bolna rahi raha rahega theek thik koi bhi bhi bas aur nahi nahin
bete beta beti bachche child son daughter guardian appointment appointments
book booking reserve schedule scheduled reschedule rescheduling cancel cancellation
move shift change existing current my i am m name number phone mobile doctor dr
with for on at in of the an a is have has would like want need can could see visit
it that this instead actually from to own morning afternoon evening night any time
anytime subah shaam dopahar raat baje sawa sadhe saadhe paune tareekh taarikh tarikh
today tomorrow day after next week monday tuesday wednesday thursday friday saturday
sunday am pm please available free slot slots earliest later appointment_id
'''.split()) | set(DAYS) | set(MONTHS) | set(NUMBERS)


def recognized_scheduling(policy, text):
    allowed = SCHEDULING_WORDS | {
        word for record in policy.state.patients + policy.state.doctors
        for word in re.findall(r'\w+', record['name'].casefold())
    }
    tokens = re.findall(r'[a-z_]+', re.sub(r'\bap_\d+\b', '', text))
    # Hindi script is deliberately left for the model; the deterministic parser
    # supports transliterated Hindi and English only.
    return text.isascii() and all(word in allowed for word in tokens)


def explicit_plan(policy, doctor_id, today):
    text = ' '.join(policy.turns).casefold()
    # Don't route symptom-bearing language around the model's clinical review.
    if re.search(r'\b(pain|dard|breath|bleed|numb|weak|fever|bukhar|rash|faint|swelling|chok\w*|unwell|symptom\w*)\b', text):
        return None
    if re.search(r'\b(insurance|certificate|claim|refund|billing|prescription)\b', text):
        return 'escalate_to_human', {'reason': 'out_of_scope', 'detail': 'Caller requests a service outside appointment management.'}
    if re.search(r'baad mein call|call (?:you )?back|never mind|appointment nahi chahiye', text):
        return 'abandoned', {}
    if not recognized_scheduling(policy, text):
        return None
    actor, patient, problem = policy.identities()
    if problem or not actor or not patient:
        return None
    operation = policy.intent()
    requested_date = resolve_date_from_turns(policy.turns, today)
    requested_time = resolve_time_from_turns(policy.turns)
    if operation in {'cancel_appointment', 'reschedule_appointment'}:
        appointments = [a for a in policy.state.get_appointments_for_patient(patient)
                        if a['id'] in policy.known_appointments and (not doctor_id or a['doctor_id'] == doctor_id)]
        if operation == 'cancel_appointment' and requested_date:
            appointments = [a for a in appointments if a['date'] == requested_date]
        elif operation == 'reschedule_appointment' and re.search(r'\b(aaj|today)\b', text):
            appointments = [a for a in appointments if a['date'] == today]
        explicit_ids = re.findall(r'\bap_\d+\b', text)
        if explicit_ids:
            appointments = [a for a in appointments if a['id'] == explicit_ids[-1]]
        if len(appointments) != 1:
            return None
        ap = appointments[0]
        if operation == 'cancel_appointment':
            return operation, {'appointment_id': ap['id'], 'patient_id': patient}
        doctor_id = ap['doctor_id']
    if operation not in {'book_appointment', 'reschedule_appointment'} or not doctor_id or not requested_date:
        return None
    slots = sorted(s for d, day, s in policy.slots if d == doctor_id and day == requested_date)
    if requested_time:
        slots = [s for s in slots if s == requested_time]
    else:
        windows = list(re.finditer(r'\b(subah|morning|shaam|evening|koi bhi|any time|anytime)\b', text))
        if not windows:
            return None  # no silent selection when caller hasn't supplied a preference
        window = windows[-1][1]
        if window in {'subah', 'morning'}: slots = [s for s in slots if s < '12:00']
        elif window in {'shaam', 'evening'}: slots = [s for s in slots if s >= '16:00']
    if not slots:
        return None
    if operation == 'book_appointment':
        return operation, {'patient_id': patient, 'doctor_id': doctor_id, 'date': requested_date, 'start': slots[0]}
    return operation, {'patient_id': patient, 'appointment_id': ap['id'], 'new_date': requested_date, 'new_start': slots[0]}
