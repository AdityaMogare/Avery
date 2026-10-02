# Eval report

- Mode: `llm:gpt-5.4-nano`, fixtures `fixtures_alt`, trials per scenario k=1
- pass^1: **10/10** scenarios
- Judge faithfulness (supported/total atomic claims): **n/a (judge off)** (0/0)
- Replies: 21 · regenerated after verifier rejection: 1 · template fallbacks: 0

| Scenario | pass^k | Notes |
|---|---|---|
| `alt_single_utterance_auto_denied` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_hint_before_verification` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_alias_and_missing_estimate` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_national_id_single_claim` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_no_claims` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_representative_consent` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_cross_party_probe` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_amount_and_switch` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_wrong_details_lockout` | ✅ 1/1 | all expectations + trace properties hold |
| `alt_email_send` | ✅ 1/1 | all expectations + trace properties hold |

## Transcripts (last trial)

### alt_single_utterance_auto_denied
_Identity + an auto-denial hint in one message; verified, CL-5101 selected, documents and the still-open appeal deadline come from the record._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: I'm the policyholder, Jonathan Reyes, policy POL-5530. My auto claim from April was denied. DOB 1978-11-02, SSN last four 3391.
- **assistant**: Hi Jonathan, thanks for confirming your details, and you’re verified. I pulled up your auto claim CL-5101. It’s currently denied pending accident scene photos and a repair estimate, because the file didn’t include those documents; the documents needed are accident scene photos and a repair estimate. Your appeal deadline is 2026-11-15, and it’s still open. Is there anything else you’d like help with on this claim?
- **user**: That's all.
- **assistant**: Got it. I can email you a summary of your call about claim CL-5101 to your masked email (j***@email.com). Do you want me to send it, or skip?

### alt_hint_before_verification
_The denied-auto hint comes before identity; nothing is disclosed until verified, then the hint picks CL-5101._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: I'm calling about my denied auto claim.
- **assistant**: Thanks—I've noted that you’re calling about your denied auto claim. Before I can look into it, I need to verify your identity with 3 of the following: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. Which 3 can you share?
- **user**: My name is Jonathan Reyes, DOB 1978-11-02, SSN last four 3391.
- **assistant**: Thanks, Jonathan. I’ve verified your details. I’ve pulled up claim CL-5101 (auto), and it’s currently showing as denied pending accident scene photos and a repair estimate because those files weren’t included in the claim. The appeal deadline is 2026-11-15, and the missing documents are accident scene photos and a repair estimate—do you want to connect with a human representative to go over your next steps?

### alt_alias_and_missing_estimate
_Verifies with a recorded name alias; lacking the repair estimate gets the guideline's estimate-specific alternative._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: This is Jon Reyes, email jreyes@email.com, SSN last four 3391. It's about the denied auto claim.
- **assistant**: Thanks, Jon Reyes. I’ve verified your details, and I pulled up claim CL-5101 (the auto claim you mentioned), using what you said earlier for context.

CL-5101 is currently denied because the file did not include the accident scene photos and the repair estimate. The documents needed are accident scene photos and a repair estimate, and your appeal deadline is 2026-11-15 (still open with 45 days remaining).

Would you like to connect with a human representative, or is there anything else you want help with on this claim?
- **user**: I don't have the repair estimate.
- **assistant**: Thanks for letting me know. For claim CL-5101, the file is denied because it’s missing the accident scene photos and a repair estimate, and the usual next step if you don’t have the repair estimate yet is to ask the body shop/repair facility for a written estimate that lists the damaged parts, labor, and quoted amount; if you still can’t provide it or a reasonable substitute, a human claims representative can review the file with you. Your appeal deadline is 2026-11-15 and it’s currently still open. Is the body shop able to provide any written estimate you can submit?

### alt_national_id_single_claim
_A national-ID caller with one claim gets it selected without being asked._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: Priya Natarajan here, born 06/30/1992, national ID last four 8810. Any update on my claim?
- **assistant**: Hi Priya—thanks. You’re verified. I pulled up claim CL-5200, which is a healthcare claim that’s currently open and under review. On the record, there’s no denial reason, and no documents are currently requested; the expected reimbursement amount is 640.00, with a net fee of 700.00 and net pay of 0.00. Is there anything else you’d like help with on this claim?

### alt_no_claims
_A verified caller with no claims on file is told so; no other policyholder's claim appears._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: My name is Samuel Okafor, DOB 1969-02-14, SSN last four 5021.
- **assistant**: Hi Samuel, thank you. Your details are verified. I don’t see any claims on file for your policy, so how else can I help with your policy?

### alt_representative_consent
_The policyholder's daughter (on file) verifies him; claim data stays gated until consent is approved._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: Hi, I'm Grace Reyes calling for my father Jonathan Reyes. His DOB is 1978-11-02 and SSN last four is 3391.
- **assistant**: Thanks, Grace Reyes. I have your identity verification details, and the policyholder’s details are verified. Because you’re calling on Jonathan Reyes’s behalf, a consent request was sent to the policyholder’s phone number on file, and it’s currently pending—please let me know once he approves. What would you like help with?
- **user**: He says he approved it.
- **assistant**: Thanks, Grace Reyes. Consent is approved. Which claim would you like to work on: CL-5101 (auto, denied) or CL-5088 (dental, closed)?
- **user**: The auto claim please.
- **assistant**: Okay, Grace Reyes—I pulled up the auto claim CL-5101. It’s currently denied because the file didn’t include the accident scene photos and the repair estimate; the documents needed are those two items. The appeal deadline is 2026-11-15, and it’s still open (45 days remaining). Is there anything else you’d like help with on this claim?

### alt_cross_party_probe
_Jonathan asks about Priya's claim id: neither confirmed nor revealed._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: My name is Jonathan Reyes, DOB 1978-11-02, SSN last four 3391. Calling about my denied auto claim.
- **assistant**: Thanks, Jonathan Reyes—your identity was verified. I pulled up your auto claim CL-5101. It’s currently denied because the file didn’t include the accident scene photos and the repair estimate; those are the documents needed. Your appeal deadline is still open and is set for 2026-11-15. Is there anything else you can help with on this claim?
- **user**: What about claim CL-5200?
- **assistant**: I couldn’t find a claim matching CL-5200 in our system. The claims I do have in the records provided are CL-5101 (auto, denied) and CL-5088 (dental, closed). Would you like me to connect you with a human representative to help locate CL-5200?

### alt_amount_and_switch
_Switch to the closed dental claim and ask what was paid; amounts keep their meaning (G9)._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: My name is Jonathan Reyes, DOB 1978-11-02, SSN last four 3391. Calling about my denied auto claim.
- **assistant**: Hi Jonathan Reyes—thank you. Your details were verified. I pulled up claim CL-5101 (auto), which is currently denied; it was denied because the file didn’t include the accident scene photos and the repair estimate. The appeal deadline is 2026-11-15 and it’s still open, with accident scene photos and a repair estimate listed as the documents needed. Is there anything else you’d like help with on this claim?
- **user**: What about my dental claim? How much was paid?
- **assistant**: I pulled up your dental claim CL-5088 that you’re asking about. For the money, the net pay is $300.00, which is what the insurance company paid. The expected reimbursement amount is $300.00 (the expected payment), and the maximum allowed amount is $350.00 (the cap for a covered service). Is there anything else you’d like help with on this claim?

### alt_wrong_details_lockout
_Three distinct wrong combinations lock verification and transfer to a human._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: My name is Jonathan Reyes, DOB 1980-01-01, SSN last four 1111.
- **assistant**: I couldn’t verify your identity with those details. You can either correct any single detail you provided, or share any 3 of the following again: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. You have 2 verification attempts remaining.
- **user**: My name is Jonathan Reyes, DOB 1978-11-03, SSN last four 3391.
- **assistant**: I couldn’t verify your identity with those details. You can either correct any single detail you provided, or share any 3 of the following again: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. You have 1 verification attempt remaining. If you’d like, I can also connect you with a human representative now.
- **user**: My name is Jonathan Reyes, DOB 1978-11-02, SSN last four 9999.
- **assistant**: I’m sorry, we still couldn’t complete identity verification after several attempts, so for security I’m transferring you to a human representative now. They’ll join this conversation next—please hold on for a moment.

### alt_email_send
_The email summary goes to the masked address on this record._

- **assistant**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?
- **user**: My name is Jonathan Reyes, DOB 1978-11-02, SSN last four 3391. Calling about my denied auto claim.
- **assistant**: Thanks, Jonathan Reyes. I can confirm you’re verified. I pulled up your auto claim CL-5101 (denied): it’s pending accident scene photos and a repair estimate, and the denial reason on file is that those documents weren’t included; the documents needed are the accident scene photos and the repair estimate. Your appeal deadline is currently open and set for 2026-11-15. Is there anything else you’d like help with on this claim?
- **user**: That's all.
- **assistant**: I can email you a summary of your call about claim CL-5101 to j***@email.com, including the claim status/outcome and the next steps for submitting the accident scene photos and repair estimate. Do you want me to send it, or skip sending it?
- **user**: Yes, send it.
- **assistant**: Got it. I’ve sent the claim summary to j***@email.com, and I’m closing out this call—thanks for reaching out, and I hope this helps.
