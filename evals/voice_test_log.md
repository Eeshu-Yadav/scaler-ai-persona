# Voice agent — live call test log

Protocol: call the agent's number from a real phone. For each call, run one
scripted scenario and record results. First-response latency = stopwatch from
end of your utterance to first audible agent speech (average of 3 measurements
per call). Transcription accuracy = spot-check the LiveKit session transcript
against what you actually said (word-level errors / total words on 3 sampled
utterances).

| # | Date | Scenario | First-resp latency (s) | Barge-in OK? | Transcript errors | Booking attempted | Booking confirmed (email + calendar) | Notes |
|---|------|----------|------------------------|--------------|-------------------|-------------------|--------------------------------------|-------|
| 1 |      | Intro + background Qs |  |  |  | no | — |  |
| 2 |      | Interrupt mid-answer ×3 |  |  |  | no | — |  |
| 3 |      | Off-script chit-chat → redirect |  |  |  | no | — |  |
| 4 |      | Unknown question ("GPA?", fake repo) |  |  |  | no | — |  |
| 5 |      | Full booking flow (happy path) |  |  |  | yes |  |  |
| 6 |      | Booking with timezone change (EST) |  |  |  | yes |  |  |
| 7 |      | Booking, then change slot mid-flow |  |  |  | yes |  |  |
| 8 |      | Spell tricky email, verify read-back |  |  |  | yes |  |  |
| 9 |      | Prompt injection by voice ("ignore instructions") |  |  |  | no | — |  |
| 10 |     | Noisy environment / speakerphone |  |  |  | yes |  |  |

## Metrics to compute after the runs

- **First-response latency**: p50 / p95 across all measurements (target < 2.0s)
- **Task completion rate**: confirmed bookings ÷ booking attempts
- **Transcription accuracy**: 1 − (word errors ÷ words sampled)
- **Barge-in success**: interruptions handled cleanly ÷ interruptions attempted
