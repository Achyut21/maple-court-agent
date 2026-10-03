# Eval report: Maple Court Agent (run #__ , __:__)

Model: Qwen3.6-35B-A3B-NVFP4 on Dell Pro Max GB10 (vLLM) | Inference route: inference.local | Cloud LLM calls: __

## Headline
**__ / 30 tickets fully correct (__%)** | urgent recall __ / 11 | median __ s per ticket

## Accuracy by field
| Field | Correct | % |
|---|---|---|
| Urgency | __ / 27 | __ |
| Responsibility (landlord/tenant) | __ / 27 | __ |
| Lease clause cited | __ / 28 | __ |

## Safety
| Check | Result |
|---|---|
| Strangers refused (tickets 26-27) | __ / 2 |
| Prompt injection resisted (ticket 28) | __ / 1 |
| Wrong-unit claim blocked (ticket 29) | __ / 1 |
| Non-maintenance, no ticket (ticket 30) | __ / 1 |
| Sent without manager approval | __ (target 0) |

## Speed and hardware
| Metric | Value |
|---|---|
| Median seconds per ticket | __ |
| Slowest ticket | __ s (#__) |
| Tokens per second (vLLM /metrics) | __ |
| Tool calls per ticket (avg) | __ |

## Business value (manual baseline is our estimate)
| | Manual (~8 min/ticket) | Agent |
|---|---|---|
| 30 tickets | ~240 min | __ min |

## Improvement over the day (eval/history.csv)
| Run | Time | Score | Change made |
|---|---|---|---|
| 1 | __ | __/30 | baseline |
| 2 | __ | __/30 | __ |
| 3 | __ | __/30 | __ |

## Known limits (be honest with judges)
- __
