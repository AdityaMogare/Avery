# Simulated-user evals

A second `gpt-5.4-nano` instance plays the caller from a persona card and a goal the agent never sees (2 personas x 3 goals x 1 runs = 6 conversations). A conversation passes when every trace property holds and the outcome is right: the right party verified (an impostor never), the right claim selected, the email choice recorded.

- Conversations passed: **6/6**
- Persona x goal cells passing all 1 runs (pass^1): **6/6**
- Mean caller turns: 3.8 · agent cost per conversation: $0.0054 · simulator cost (whole run): $0.00

| Persona \ goal | denied_claim | auto_amount | representative |
|---|---|---|---|
| calm | 1/1 | 1/1 | 1/1 |
| angry | 1/1 | 1/1 | 1/1 |

## Failures

None.
