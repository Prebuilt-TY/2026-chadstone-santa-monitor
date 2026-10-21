# Chadstone Santa Photography — booking cancellation monitor

**Status (21 Oct 2026): ACTIVE, safety-first scheduled scans configured.**

- Official booking website: https://www.chadstone.com.au/christmas/santa-photos
- **Standard Santa Photography 2026** only (NOT Sensitive Santa).
- **4 November to 15 December 2026, inclusive**, any time, Melbourne local time.
- GitHub Actions schedule requests a scan **every 5 minutes**; GitHub may delay or skip scheduled runs (often more than 5 minutes between executions).
- When a confirmed available date **and a specific clickable time** are found, send a ntfy phone notification (no automatic booking or payment).
- The exact time-selection interface has **not been validated with an actual available slot** because all target dates were fully unavailable during testing. If the time control isn't recognisable, the monitor **fails closed** (no misleading notifications). GitHub Actions run logs reveal errors.

## Current validation
On 21 Oct, the full calendar dry-run opened the official 2026 Santa Photography modal, navigated November and December, inspected every date in the target range and found **zero selectable dates**. Python compilation and five parsing tests passed. Phone TEST ONLY delivery was independently confirmed.

The scheduled monitor reads both months on every active run. It requires a clickable non-crossed-out target date AND a specific enabled clickable time. If the website changes, the scan errors instead of reporting a fake opening. The time-slot detection remains provisional until an actual cancellation produces a selectable date.

## Phone notifications
1. Install [ntfy](https://ntfy.sh/), allow notifications, and subscribe to an unguessable random topic (24-120 letters/numbers/`_`/`-`). Topics on the hosted public service are accessible to anyone who knows the topic.
2. Add the same topic string (not the full URL) to GitHub Repository **Settings > Secrets and variables > Actions** as the secret named `NTFY_TOPIC`.
3. In [Actions](../../actions/workflows/santa.yml) manually run mode `test-push` to verify delivery. This sends a test message, never a booking claim.

## Diagnostics and manual testing
- Workflow: [Chadstone Santa availability](../../actions/workflows/santa.yml)
- **probe**: captures a calendar inspection of November and December, with screenshots and `month-status.json`. It never books a session.
- **dry-run** (CLI only): scans the real target dates, displays candidate times without ntfy or state updates. A dry run executes as part of [Validate Santa monitor](../../actions/workflows/validate.yml) on changes to main.
- **monitor**: sends alerts only on verified, newly appearing time slots; stores the last successful complete snapshot in `state.json`.
- **test-push**: sends a clearly labelled test notification.

## Limits and safety
The date-availability logic has been validated using the actual booked-out calendar. No real available day/time sample has yet appeared to validate the final clickable-time confirmation. Failure to recognise an available date or a website anti-automation challenge can cause missed notifications. Do not use automation to bypass access controls. Scheduled jobs may be delayed or dropped by GitHub; a five-minute cron is not a guarantee. Repeated scans should respect the booking site's access limits. Public repo content and action logs are visible. Disable the workflow after 15 December 2026.
