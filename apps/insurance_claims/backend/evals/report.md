# Eval report

- Mode: `offline`, fixtures `fixtures`, trials per scenario k=1
- pass^1: **2/2** scenarios
- Judge faithfulness (supported/total atomic claims): **n/a (judge off)** (0/0)
- Replies: 7 · regenerated after verifier rejection: 0 · template fallbacks: 0

| Scenario | pass^k | Notes |
|---|---|---|
| `margaret_demo_single_utterance` | ✅ 1/1 | all expectations + trace properties hold |
| `edge_switch_back` | ✅ 1/1 | all expectations + trace properties hold |

## Transcripts (last trial)

### margaret_demo_single_utterance
_Context.md demo test case: identity + case hint in one utterance, then grounded follow-up and email._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.
- **assistant**: Thank you, Margaret Chen, you're verified. I've pulled up claim CL-2048. Claim CL-2048 is a healthcare claim created on 2026-01-12, and its status is denied: Healthcare claim denied due to missing pathology report and office note. It was denied because the review file did not include the pathology report and the treating provider office note. To reconsider it, the review needs: pathology report, office note. The appeal deadline on record was 2026-03-18, which has passed as of today (2026-10-01). Options after a passed appeal deadline are reviewed by a human representative, and I can connect you if you'd like. Is there anything else I can help you with on this claim?
- **user**: Why was it denied and what do I need to send?
- **assistant**: Claim CL-2048 is a healthcare claim created on 2026-01-12, and its status is denied: Healthcare claim denied due to missing pathology report and office note. It was denied because the review file did not include the pathology report and the treating provider office note. To reconsider it, the review needs: pathology report, office note. The appeal deadline on record was 2026-03-18, which has passed as of today (2026-10-01). Options after a passed appeal deadline are reviewed by a human representative, and I can connect you if you'd like. Is there anything else I can help you with on this claim?
- **user**: That's all, thanks.
- **assistant**: Before you go, would you like me to email a summary of our conversation, including what we discussed, the claim status and next steps, to m***@email.com? Just say send or skip.
- **user**: Yes, please send it.
- **assistant**: Done. I've sent the summary to m***@email.com. Thank you for calling!

### edge_switch_back
_Switching to the auto claim and back to the denied claim restores the right case each time._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: My name is Margaret Chen, DOB 1985-03-15, SSN last four 4472. I'm calling about my denied healthcare claim from January.
- **assistant**: Thank you, Margaret Chen, you're verified. I've pulled up claim CL-2048. Claim CL-2048 is a healthcare claim created on 2026-01-12, and its status is denied: Healthcare claim denied due to missing pathology report and office note. It was denied because the review file did not include the pathology report and the treating provider office note. To reconsider it, the review needs: pathology report, office note. The appeal deadline on record was 2026-03-18, which has passed as of today (2026-10-01). Options after a passed appeal deadline are reviewed by a human representative, and I can connect you if you'd like. Is there anything else I can help you with on this claim?
- **user**: What about my auto claim?
- **assistant**: I've pulled up claim CL-2102. Claim CL-2102 is an auto claim created on 2026-02-28, and its status is open: Auto claim in progress. The expected reimbursement is $3200.00 and the amount paid so far is $0.00. Is there anything else I can help you with on this claim?
- **user**: OK, back to the denied one. What documents do I need?
- **assistant**: I've pulled up claim CL-2048. Claim CL-2048 is a healthcare claim created on 2026-01-12, and its status is denied: Healthcare claim denied due to missing pathology report and office note. It was denied because the review file did not include the pathology report and the treating provider office note. To reconsider it, the review needs: pathology report, office note. The appeal deadline on record was 2026-03-18, which has passed as of today (2026-10-01). Options after a passed appeal deadline are reviewed by a human representative, and I can connect you if you'd like. Is there anything else I can help you with on this claim?
