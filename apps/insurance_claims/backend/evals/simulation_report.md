# Simulated-user evals

A second `gpt-5.4-nano` instance plays the caller from a persona card and a goal the agent never sees (1 personas x 2 goals x 1 runs = 2 conversations). A conversation passes when every trace property holds and the outcome is right: the right party verified (an impostor never), the right claim selected, the email choice recorded.

- Conversations passed: **1/2**
- Persona x goal cells passing all 1 runs (pass^1): **1/2**
- Mean caller turns: 7.5 · agent cost per conversation: $0.0119 · simulator cost (whole run): $0.00

| Persona \ goal | denied_claim | impostor |
|---|---|---|
| angry | 0/1 | 1/1 |

## Failures

### angry / denied_claim (2 turns, ended in HUMAN_TRANSFER)
- outcome: email choice None, expected send

> **agent**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?  
> **caller**: This is Margaret Chen, DOB 1985-03-15, and the last four of my SSN is 4472. I need answers on why my January healthcare claim was denied—don’t make me jump through hoops; tell me what you need and what the decision is based on.  
> **agent**: I’m sorry you’re dealing with a denial; that’s frustrating. Thanks, Margaret Chen—you’ve been verified, and I have your identity details on file. I pulled up healthcare claim CL-2048, which was denied because the review file didn’t include a pathology report and the treating provider office note. The expected reimbursement amount is 0.00, and since the appeal deadline has passed, your options are reviewed by a human representative on request—would you like me to connect you to one, and if so, do you have the pathology report and the office note available to submit now?  
> **caller**: Yes, connect me to a human rep. I wasn’t told I was missing those items—what exactly do you need for the pathology report and the provider office note, and can you email me a summary of the denial and the submission requirements?  
> **agent**: I’m really sorry you weren’t told what was missing—that’s frustrating. I’m connecting you to a human customer service representative now so they can explain the denial and tell you exactly what to provide for the pathology report and provider office note. I can also help with emailing a summary of what they need as part of the handoff—would you like the summary sent to your email on file?  

