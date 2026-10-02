# Judge calibration

The groundedness judge (`gpt-5.4-nano`, 3 run(s) per row, majority vote) against 42 labelled replies in `judge_labels.jsonl`.

| Metric | Value |
|---|---|
| Agreement with labels | **93%** (42 scored) |
| Cohen's kappa | 0.86 |
| Recall on ungrounded replies | 86% |
| Precision on ungrounded replies | 100% |
| Judge cost for this run | $0.0525 (126 calls) |

Confusion: human=grounded judge=grounded: 20, human=ungrounded judge=grounded: 3, human=ungrounded judge=ungrounded: 19

Labels were written by the author (with AI assistance) against the fact sheet the agent holds; they should be reviewed by a second person before the agreement number is relied on.

## Disagreements

- **h05** (label ungrounded, judge grounded, votes ['grounded', 'grounded', 'grounded']): "Your claim was denied in January." (hard: record has creation date, not a denial date)
- **h10** (label ungrounded, judge grounded, votes ['grounded', 'grounded', 'grounded']): "It was denied because your provider forgot to send the pathology report and the office note." (hard: blame on the provider is not in the record)
- **h12** (label ungrounded, judge grounded, votes ['grounded', 'grounded', 'grounded']): "Your plan covers up to $1,450.00 per year." (hard: per-claim cap turned into an annual plan limit)
