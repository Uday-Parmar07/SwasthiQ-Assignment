# Final submission checklist

## Ready in the repository

- Python backend, six tools, and React queue/detail screens.
- Eight adversarial scripts with expected outcomes and explanations.
- One-command launcher, API contract, decisions, and measured per-conversation report.
- CI covering backend regressions, three-run assessment evaluation, and frontend build.
- Current repair-session prompts with explicit provenance.

## Candidate-owned items to finish or verify

- Confirm the repository is public and push the reviewed changes.
- Deploy `render.yaml` (or equivalent), configure provider keys privately and set the frontend build-time
  `VITE_API_BASE_URL` to the backend public HTTPS URL, then record
  the real frontend URL. Check simulation → detail → queue → Resolve on that URL.
- Export earlier coding-assistant prompts; the earlier source transcript was not
  present in the provided repository.
- Record/upload a three-minute failure-analysis video and test its link without login.
- Supply full name and actual hours worked. Check the original three-day deadline.

## Suggested three-minute failure-analysis video

0:00–0:40: Explain the original emergency-plus-injection bug. Show the old failure
and the regression that now requires `clinical_urgent`, no appointment mutation.

0:40–1:30: Explain why a patient ID supplied by a model is not authorization. Show
an unauthorized proxy being handed off and Meera/Kabir being resolved correctly.

1:30–2:20: Break the language boundary using an unfamiliar clinical paraphrase or
unsupported date wording. Explain which deterministic patterns cover it, which
inputs need the model, and that the model/provider can still fail. Do not portray
all hidden cases as solved merely because the visible scripts pass.

2:20–3:00: Show the measured report and the concurrency ambiguity: shared-state
mutations are atomic, but the evaluation contract resets state per request.
Describe the next four hours: broaden semantic/negation cases, evaluate unseen
paraphrases with the actual provider, and test deployment recovery.

## Email draft (fill in factual values; not sent)

To: hiring@swasthiq.in
Subject: Engineering Assignment - [Your Full Name]

Repository: https://github.com/Uday-Parmar07/SwasthiQ-Assignment
Live application: [verified public URL]
Failure-analysis video: [verified public URL without login]

I spent approximately [actual hours] hours on the assignment. With another four
hours I would [your own priorities, informed by the documented remaining limits].

[Your Full Name]
