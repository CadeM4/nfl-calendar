These are reduced factual JSON hydration records retrieved from the public NFL
schedule on September 27, 2026 (UTC). Unused presentation, advertising, audio,
standings, and coverage-map DMA fields were removed. Tests reconstruct the
surrounding Next.js Flight framing, including records split across scripts.

- `nfl-week-3.json`: https://www.nfl.com/schedules/2026/by-week/week-3
- `nfl-week-18.json`: https://www.nfl.com/schedules/2026/by-week/week-18
- `nfl-2025-superbowl.json`: https://www.nfl.com/schedules/2025/by-week/super-bowl-sunday

The historical Super Bowl verifies the source's POST week 4 / weekType SB
convention, normalized internally to playoff week 5. Fixtures are test inputs,
never a replacement for a successful live refresh.
