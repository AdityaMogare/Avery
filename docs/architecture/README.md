# Architecture diagrams

Source files (`*.mmd`) render on GitHub, in VS Code (Mermaid preview) or at https://mermaid.live.

| File | Shows |
|---|---|
| `01-system-overview.mmd` | Components: React SPA, FastAPI turn pipeline, fixtures, OpenAI |
| `02-sop-state-machine.mmd` | The deterministic SOP phases, gates and global guards |
| `03-turn-sequence.mmd` | One turn: understand → controller → tools → respond → verify |
| `04-grounding-and-evaluation.mmd` | Runtime grounding loop and the four test/eval layers |
