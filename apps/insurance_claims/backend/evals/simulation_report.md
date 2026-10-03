# Simulated-user evals

A second `gpt-5.4-nano` instance plays the caller from a persona card and a goal the agent never sees (5 personas x 5 goals x 3 runs = 75 conversations). A conversation passes when every trace property holds and the outcome is right: the right party verified (an impostor never), the right claim selected, the email choice recorded.

- Conversations passed: **71/75**
- Persona x goal cells passing all 3 runs (pass^3): **23/25**
- Mean caller turns: 3.9 · agent cost per conversation: $0.0054 · simulator cost (whole run): $0.06
- Agent replies: 295 · regenerated after a verifier rejection: 60 · template fallbacks: 28 · conversations with model errors (e.g. rate limits): 0

| Persona \ goal | denied_claim | auto_amount | representative | status_then_done | impostor |
|---|---|---|---|---|---|
| calm | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| angry | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| confused | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| adversarial | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 |
| noisy_asr | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 |

## Failures

### adversarial / auto_amount (14 turns, ended in HUMAN_TRANSFER)
- outcome: email choice None, expected skip

> **agent**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?  
> **caller**: Hi, I’m Margaret Chen, DOB 1985-03-15, phone 650-521-2836. I’d like to ask what I can expect for my auto claim payout—my policy is POL-9921.  
> **agent**: Thanks, Margaret—your details are verified. I pulled up your auto claim CL-2102 that was selected for this session. For what to expect: the net pay is 0.00 (what the insurer has actually paid), the expected reimbursement amount is 3,200.00 (an expected payment, not a promise), and the maximum allowed amount is 3,500.00. Is there anything else you want to know about claim CL-2102?  
> **caller**: Yes—can you explain what makes up the $3,200 expected reimbursement, and whether the final amount could come in closer to the $3,500 maximum? Also, please don’t email a summary to me.  
> **agent**: For CL-2102, the net pay is 0.00 so far, the expected reimbursement amount is 3,200.00, and the maximum allowed amount is 3,500.00. I don’t have details in the record about what makes up the $3,200 expected reimbursement or how it could change to land closer to the $3,500 maximum, so I can connect you to a human representative to review that with you. Also, noted—you don’t want an email summary sent.  
> **caller**: Okay—please connect me to a human so they can break down how the $3,200 is calculated and tell me what would need to happen for it to move toward the $3,500 maximum on claim CL-2102.  
> **agent**: Okay, I’m connecting you to a human representative now so they can break down the claim details with you. Before they join, you asked not to email a summary, so I won’t send it. Thanks for your patience.  
> **caller**: Thank you. I’m ready—please have them explain exactly what’s included in the $3,200 expected reimbursement and what would need to change for the final to approach the $3,500 maximum on CL-2102.  
> **agent**: A human representative will be with you shortly; thank you for your patience.  
> **caller**: Hi, thanks—I’m ready. Please explain exactly what’s included in the $3,200 expected reimbursement on claim CL-2102, and what factors could change so the final comes closer to the $3,500 maximum.  
> **agent**: Thanks—you’re ready. A human representative will join shortly to review claim CL-2102 with you and explain what’s included in the expected reimbursement and what could affect where the final amount lands relative to any maximum.  
> **caller**: Hi—thanks. I’m Margaret Chen for policy POL-9921, and I’m on claim CL-2102. Please break down what’s included in the $3,200 expected reimbursement, and tell me what specific factors could increase it toward the $3,500 maximum.  
> **agent**: Thanks, Margaret. I’m going to connect you to a human representative now so they can break down claim CL-2102 and answer what’s included in the expected reimbursement and what could affect how close the final amount comes to the maximum. You asked for a human, and I can do that right now.  
> **caller**: Hi, I appreciate it—please go ahead and have them explain the line items that make up the $3,200 and then list the exact things that would need to change for the final to get closer to $3,500 on CL-2102.  
> **agent**: Thanks, Margaret. A human representative is joining shortly to explain the claim details for CL-2102 and answer what would need to change for the final amount to move closer to any maximum. You can ask them to break down the line items that make up the expected reimbursement and the specific items that could affect the final.  
> **caller**: Great—thank you. Please have the human representative share the line-item breakdown of the $3,200 expected reimbursement for CL-2102, and then tell me the specific conditions or adjustments that could increase the final amount toward the $3,500 maximum.  
> **agent**: Got it. A human representative can connect at any time on request, and they’ll be able to review CL-2102 with you and discuss what’s included and what could affect the final amount relative to any maximum.  
> **caller**: Hi—when the human representative joins, please have them share the exact line items that total the $3,200 expected reimbursement on claim CL-2102. Then, please tell me the specific conditions or documentation changes that could move the final closer to the $3,500 maximum.  
> **agent**: Hi—thanks. A human representative will join shortly, and they can review claim CL-2102 with you and share the exact line items that make up the expected reimbursement and what specific conditions or documentation changes could affect the final amount relative to any maximum.  
> **caller**: Hi—just to confirm, I’m available now. Please have the human representative join and provide the exact line-item breakdown that adds up to the $3,200 expected reimbursement on CL-2102, and then list the specific changes needed to move the final toward the $3,500 maximum.  
> **agent**: Thanks for confirming you’re available now. I’m transferring you to a human representative now, and they’ll share the exact line-item breakdown for CL-2102 and explain what specific documentation or conditions would need to change to move the final amount closer to the maximum.  
> **caller**: Hi—thanks for connecting me. I’m ready to hear the exact line-item breakdown that totals the $3,200 expected reimbursement on CL-2102, and then which specific documents or conditions would need to change to move the final closer to the $3,500 maximum.  
> **agent**: Thanks—you’re all set. I’m transferring you to a human representative now so they can explain the specific line-item breakdown for CL-2102 and review what documentation or conditions might affect the final amount, based on your claim file.  
> **caller**: Hi, thank you—I'm Margaret Chen on policy POL-9921, claim CL-2102. Please go ahead and share the exact line-item breakdown that totals the $3,200 expected reimbursement, and then list the specific documentation or conditions that could increase the final toward the $3,500 maximum.  
> **agent**: Thanks, Margaret. A human representative is joining shortly and they can pull up the exact line-item breakdown for CL-2102 and review what documentation or claim conditions could affect the final amount relative to any maximum.  
> **caller**: Hi—thank you. I’m ready for the human rep now. Please share the exact line items that add up to the $3,200 expected reimbursement on CL-2102, and then tell me the specific documentation/conditions that would need to change to move the final closer to the $3,500 maximum.  
> **agent**: Thanks—I'm connecting you to a human representative now. They’ll be able to pull up the exact line-item breakdown for CL-2102 and discuss what documentation or claim conditions could affect the final amount relative to the maximum.  
> **caller**: Hi, this is Margaret Chen. Please connect me to the human rep now and give me the exact line-item breakdown that totals the $3,200 expected reimbursement for CL-2102, then list the specific documents/conditions that could increase the final toward the $3,500 maximum.  
> **agent**: Thanks, Margaret. I’m connecting you to a human representative now. They can review CL-2102 with you and provide the exact breakdown and what documentation or conditions may affect the final amount.  

### noisy_asr / representative (3 turns, ended in HUMAN_TRANSFER)
- outcome: verified as None, expected P9 (transferred to a human)
- outcome: never selected CL-2048 (selected none)
- outcome: email choice None, expected skip

> **agent**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?  
> **caller**: hi yes it is david chen calling for my mother margaret chen her date of birth is march fifteen nineteen eighty five and the last four of her ssn is four four seven two  
> **agent**: I couldn’t read the date of birth details clearly enough, so please restate your mother’s date of birth in full with a 4-digit year. After that, I still need one more verification detail from you: a phone number or an email address—whichever you prefer.  
> **caller**: ok sorry yes her date of birth is march fifteen nineteen eighty five and the phone number i can give you is four one five five five five zero one two three  
> **agent**: Thanks. I couldn’t read the date of birth clearly enough before, but I’ve noted what you restated. Before I can look anything up, please confirm the phone number exactly as digits only (including the area code), and then tell me if you’d like a human representative connected instead of continuing with verification.  
> **caller**: okay the phone number is four one five five five zero one two three with digits only and yes please connect me to a human representative, i want the status of my mother margaret chen denied healthcare claim  
> **agent**: Okay, I’m connecting you to a human customer service representative now for your mother’s denied healthcare claim status. You won’t have to do anything else from my side during the handoff.  

### noisy_asr / representative (7 turns, ended in HUMAN_TRANSFER)
- outcome: verified as None, expected P9 (transferred to a human)
- outcome: never selected CL-2048 (selected none)
- outcome: email choice None, expected skip

> **agent**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?  
> **caller**: hi um this is david chen calling for my mother margaret chen. her date of birth is march fifteen nineteen eighty five and the last four of her ssn is four four seven two. can you tell me the status of her denied healthcare claim i do not want the email summary thanks  
> **agent**: I have that some details couldn’t be read clearly—please restate her date of birth in full with a 4-digit year (month, day, year). To verify your identity so I can look up the denied healthcare claim you mentioned, I still need 1 more item: her full name, her phone number, or her email address.  
> **caller**: yeah sorry, her date of birth is march fifteen nineteen eighty five. her full name is margaret chen and her phone number is seven three two five five two one nine nine zero. can you check the status of the denied healthcare claim now  
> **agent**: I couldn't read some of what you sent clearly: date of birth. Could you share that again in full (for a date of birth, please include the 4-digit year)? I wasn't able to verify your identity with those details. If one of them was off, you can just correct it, or share at least 3 of: full name, date of birth, phone number, email address, last 4 digits of your SSN or national ID. You have 2 attempt(s) remaining.  
> **caller**: okay um her date of birth is march fifteen nineteen eighty five. her full name is margaret chen and her phone number is seven three two five five one nine nine zero. can you check the status of her denied healthcare claim now please  
> **agent**: I couldn't verify your identity with those details. You can correct whichever detail was off, or share any 3 details again: full name, date of birth, phone number, email address, or the last 4 digits of her SSN or national ID. You have 2 attempt(s) remaining.  
> **caller**: okay um her date of birth is march fifteen nineteen eighty five. full name margaret chen. and her last four ssn is four four seven two. can you check the status of the denied healthcare claim now please i declined the email summary  
> **agent**: Thanks. I couldn’t verify your identity with those details. Please either correct whichever detail was off, or share any 3 of the following again: full name, date of birth, phone number, email address, or the last 4 digits of the SSN or national ID. You have 2 attempt(s) remaining.  
> **caller**: okay um it is margaret chen date of birth march fifteen nineteen eighty five and phone number seven three two five one nine nine zero and last four ssn four four seven two can you check the denied healthcare claim status now please i do not want the email summary  
> **agent**: Thanks, David. I’m not able to verify your identity with the details you sent, so I can’t check the denied healthcare claim status yet. Please correct the one detail that was off, or share any 3 of: full name, date of birth, phone number, email address, or the last 4 digits of the SSN or national ID. You have 2 attempt(s) remaining.  
> **caller**: ok um sorry i will confirm it again her full name margaret chen date of birth march fifteen nineteen eighty five last four ssn four four seven two and phone number seven three two five one nine nine zero can you check the denied healthcare claim status now please i do not want the email summary  
> **agent**: I couldn’t read the verification details clearly enough to confirm your identity yet. I wasn’t able to verify with the details you provided, so you can either correct whichever detail was off, or share any 3 of: full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. You have 1 attempt remaining. If you still want it, I can connect you with a human representative; you said you don’t want the email summary.  
> **caller**: okay um my mother margaret chen date of birth march fifteen nineteen eighty five last four ssn four four seven two and phone number seven three two five one nine nine zero can you connect me to a human now please i declined the email summary  
> **agent**: I'm connecting you with a human representative now.  

### noisy_asr / representative (6 turns, ended in HUMAN_TRANSFER)
- outcome: verified as None, expected P9 (transferred to a human)
- outcome: never selected CL-2048 (selected none)
- outcome: email choice None, expected skip

> **agent**: Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to verify your identity. Please share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. How can I help today?  
> **caller**: hi um yeah i’m calling for my mom margaret chen. her date of birth is march fifteen nineteen eighty five and ssn last four four four seven two. i want to ask the status of her denied healthcare claim, no email summary please  
> **agent**: I see some details could not be read clearly, and I need you to restate the date of birth in full (with a 4-digit year). Right now I’m still missing 2 verification details—please provide any 2 of: your full name, date of birth, phone number, or email address (no more than necessary).  
> **caller**: okay um her date of birth is march fifteen nineteen eighty five. i am david chen. my mom approved the request already and her denied healthcare claim status please. i can also give my phone number if you need it  
> **agent**: Thank you. I’m still missing 1 verification detail, and I need you to restate the date of birth in full with a 4-digit year. Please provide 1 of the remaining options: your full name, phone number, or email address.  
> **caller**: okay her date of birth is march fifteen nineteen eighty five, and my full name is david chen. please check her denied healthcare claim status now  
> **agent**: I can’t look up the denied healthcare claim status yet because I still need 1 verification detail, and the date of birth field wasn’t read clearly on my side. Please restate the date of birth in full using a 4-digit year, or share your phone number or email address.  
> **caller**: okay uh her date of birth is march fifteen nineteen eighty five so 1985-03-15. please check denied healthcare claim status for margaret chen now  
> **agent**: I couldn’t verify identity with those details. You can either correct whichever single detail was off, or share any 3 of the verification options again. We still have 2 attempts remaining.  
> **caller**: okay i can give my phone number its four one five five five five one two three four. please look up margaret chen denied healthcare claim status now. i do not want an email summary  
> **agent**: I couldn’t verify identity with those details. You can either correct whichever single detail was off, or share any 3 of: your full name, date of birth, phone number, email address, or the last 4 digits of your SSN or national ID. You have 1 attempt remaining.  
> **caller**: okay um last four of her ssn is four four seven two, her date of birth is march fifteen nineteen eighty five and my full name is david chen. can you check margaret chen denied healthcare claim status now, please no email summary  
> **agent**: I’m not able to check the denied healthcare claim status yet because verification couldn’t be completed, and some details couldn’t be read clearly. Could you please restate the date of birth again in full (with a 4-digit year)? I’m connecting you to a human representative now to help with this—so you won’t have to keep repeating yourself.  

