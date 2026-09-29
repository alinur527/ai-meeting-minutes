# Historical product comparison — HackAlem Track 8

Review date: September 29, 2026. Teams were discovered through [HackAlem Atlas, Track 8](https://govnejri.github.io/hackalem-atlas/#t8), after Exit 1's real API and browser baseline worked. Public READMEs were reviewed; closely related filters were also checked in source. Other teams' applications and models were not run. This is a design comparison, not a ranking or an independent accuracy / performance benchmark.

## Related approaches

| Team / source | Reported product ideas | Relationship to AI Meeting Minutes |
|---|---|---|
| [Saint Tibo](https://github.com/BAITC-Hacks/hack-a58598e0-saint-tibo#readme) | Protocol revisions; distinct speaker / task-owner roles; speaker filtering and sequential playback; briefing / reminders | Speaker mapping, task ownership, evidence, confirmation and DOCX already existed. Speaker filtering was selected; revisions and briefing remain future work. |
| [Lahmut Group](https://github.com/BAITC-Hacks/hack-b112b722-lahmut-group#readme) | Review panel, meeting search, task registry with status / overdue filters and optional Telegram | Meeting history and task review already existed. Filtering was adapted within a single meeting; an execution registry and Telegram were deferred. |
| [MNIST](https://github.com/BAITC-Hacks/hack-2b778d9f-mnist#readme) | Evidence-backed minutes, transcript editing, manual tasks, persistent player and DOCX / PDF | Existing evidence navigation and review were retained. Transcript editing needs revision handling; PDF remains future work. Its README noted an authentication / roles limitation. |
| [Be LIke AI](https://github.com/BAITC-Hacks/hack-cd51b8b1-be-like-ai#readme) | Decisions, risks, open questions, coverage checks, task statuses / overdue state, review flags and export | Review-state filtering was useful immediately. New LLM entities and task execution lifecycles were deferred. |
| [Sandwich](https://github.com/BAITC-Hacks/hack-207ff40c-team#readme) | Task-to-recording navigation, manual evidence-backed review, version attribution and multiple exports | Reinforced using one reviewed record as the export source. Versioning and ICS were deferred; some of the team's demo material was synthetic. |
| [KaskyrAlmaty](https://github.com/BAITC-Hacks/hack-d7cbffb9-kaskyralmaty#readme) | Whisper plus a separate Kazakh SeamlessM4T pass, validation / retry, microphone / tab capture, history and DOCX | Validate Russian / Kazakh / mixed speech first. Adding another model now would increase memory and latency without a measured benefit for this project. |

Source checks: Saint Tibo's [TranscriptPanel](https://github.com/BAITC-Hacks/hack-a58598e0-saint-tibo/blob/main/frontend/src/shared/ui/transcript-sync/transcript-panel.tsx) implements `speakerFilter`. Lahmut Group's [App.tsx](https://github.com/BAITC-Hacks/hack-b112b722-lahmut-group/blob/main/frontend/src/App.tsx) includes meeting search and task status / overdue filters. These sources do not establish that Lahmut implemented transcript search or the exact task-owner filter added here.

## Three implemented improvements

| Feature | Rationale / attribution | Behavior and risk control |
|---|---|---|
| Transcript search with match highlighting | Requested product improvement; an original extension of evidence review, not an exact feature attributed to another team's README | Find names, deadlines or discussion points. Source navigation clears filters and restores focus. React renders text without inserting raw HTML. |
| Speaker filter | Inspired by Saint Tibo's documented and source-verified UI | Focus on a voice while retaining its original label and mapped participant. Filtering does not change task ownership or speaker mapping. |
| Task filters by owner / needs-review | Adapted from Lahmut's task registry concept and Be LIke AI's review flags | Isolate uncertain tasks before confirmation. Filters are disabled during an edit; DOCX always includes the complete confirmed record. |

These changes use the existing transcript, task and meeting components without new models, schema migrations or public API changes. They were checked in browser regressions and the real browser workflow; see [verification](VERIFICATION.md).

## Existing strengths and deferred work

Exit 1 already supported timestamped evidence / playback, task owners and raw / normalized deadlines, speaker mapping, manual task review, meeting history, failed-only retry, confirmation / reopening and DOCX. Its verified engineering work includes account ownership checks, CSRF, lease recovery / fencing, preserved edits and backup restoration. These are specific tested properties, not a claim of superiority over other teams.

Detailed live AI stage progress, continuous transcript playback highlighting, versioned transcript edits, decisions / risks / open questions, a cross-meeting task registry and external integrations remain future work. Language-model configuration alone does not establish Russian / Kazakh / mixed-language accuracy.

The comparison informed design choices; large sections of other teams' source code were not copied. Their claims and preliminary metrics are not this project's measurements. The public project preserves the original Exit 1 attribution.
