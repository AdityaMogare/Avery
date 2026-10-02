# Eval report

- Mode: `llm:gpt-5.4-nano`, fixtures `fixtures`, trials per scenario k=2
- pass^2: **2/2** scenarios
- Judge faithfulness (supported/total atomic claims): **n/a (judge off)** (0/0)
- Replies: 14 · regenerated after verifier rejection: 0 · template fallbacks: 1

## Cost and latency (agent turns, judge excluded)

| Metric | Value |
|---|---|
| Turn latency p50 / p95 (wall, incl. understand + respond + any regeneration) | 4014 ms / 5102 ms |
| Model calls per turn (mean) | 2.07 |
| Tokens per turn / per conversation (mean) | 4,040 / 14,142 |
| Estimated cost per conversation | $0.0043 ($4.28 per 1,000) |

Prices: gpt-5.4-nano list price, USD per 1M tokens: input 0.2, cached input 0.02, output 1.25 (override with PRICE_*_PER_M).

| Scenario | pass^k | Notes |
|---|---|---|
| `margaret_demo_single_utterance` | ✅ 2/2 | all expectations + trace properties hold |
| `edge_switch_back` | ✅ 2/2 | all expectations + trace properties hold |

## Transcripts (last trial)

### margaret_demo_single_utterance
_Context.md demo test case: identity + case hint in one utterance, then grounded follow-up and email._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.
- **assistant**: Thanks, Margaret. You’re verified, and I’ve pulled up your healthcare claim CL-2048. It was denied because the review file didn’t include the pathology report and the treating provider office note, and the documents needed are those two items. Your appeal deadline has passed, so options after a passed appeal deadline are reviewed by a human representative, and you can ask to be connected; would you like me to transfer you to one now?
- **user**: Why was it denied and what do I need to send?
- **assistant**: Your healthcare claim CL-2048 was denied because the review file didn’t include the pathology report and the treating provider office note. To address that, you’ll need to send a pathology report and the treating provider office note. Since the appeal deadline status is passed, options after a passed appeal deadline are reviewed by a human representative, and you can ask to be connected—would you like me to transfer you to a human representative?
- **user**: That's all, thanks.
- **assistant**: Got it, Margaret. I can email you a summary of your call, including the denial reason and the next steps for claim CL-2048, to m***@email.com—would you like me to send it or skip sending it?
- **user**: Yes, please send it.
- **assistant**: Thanks. I’ve sent the summary to m***@email.com. Take care, and thanks for calling claims support.

### edge_switch_back
_Switching to the auto claim and back to the denied claim restores the right case each time._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: My name is Margaret Chen, DOB 1985-03-15, SSN last four 4472. I'm calling about my denied healthcare claim from January.
- **assistant**: Thanks, Margaret Chen. I can confirm your details were verified, and I pulled up your healthcare claim CL-2048. It’s currently denied because the review file didn’t include the pathology report and the treating provider office note. The appeal deadline has passed, so options after a passed appeal deadline are reviewed by a human representative, and I can connect you if you’d like—would you like me to do that?
- **user**: What about my auto claim?
- **assistant**: Okay, I switched to your auto claim CL-2102. It’s currently open and in progress, with an expected reimbursement amount of $3,200.00 and an allowed max amount of $3,500.00. Do you want me to connect you to a human representative, or is there a specific question you have about this auto claim?
- **user**: OK, back to the denied one. What documents do I need?
- **assistant**: For your denied healthcare claim CL-2048, you’ll need the pathology report and the treating provider’s office note, because the review file didn’t include those documents. The appeal deadline has passed, and options after a passed appeal deadline are reviewed by a human representative if you want a transfer—would you like me to connect you?
