# Chadstone Santa Photography 2026 Monitor

**Status: Deployed in safety-off mode; real calendar calibration pending.**

Official site: https://www.chadstone.com.au/christmas/santa-photos

Settings: Standard Santa Photography only; **4 November–15 December 2026** inclusive; any time, Melbourne timezone. GitHub Actions best-effort five-minute schedule, ntfy mobile push. No automatic booking or payment.

## Step 1: Run a real-page diagnostic
1. Visit [Actions](../../actions/workflows/santa.yml).
2. Choose **Run workflow**, set mode to **probe**, press Run workflow.
3. Open the run. Download **chadstone-diagnostic** artifact within one day; it contains `probe.json` and screenshots.
4. Probe visits the official page and clicks the first visible Book Now control. This has **not** been verified as the Standard appointment calendar. Do not assume probe output showing a button means real availability. Check diagnostic files for personal details before sharing.

## Step 2: Calibrate booking calendar (mandatory)
The program starts with `enabled: false`, `full_date_range_verified: false` and blank CSS selectors. It will **not** send real availability alerts until the actual Standard-only booking interface is validated, accurate full ISO date/time values are extracted, and all dates 4 Nov–15 Dec are traversed. The current starter does not navigate calendar months/weeks automatically. A booking-provider-specific navigation adapter may be necessary. CAPTCHA/login/bot barriers must not be bypassed.

Only after site-specific validation set `enabled: true` and verified Standard-only `standard_scope_selector`, `slot_selector`, `empty_state_selector`, `calendar_frame_url_contains`, `slot_datetime_attribute`, `full_date_range_verified: true` in config.json. An ambiguous or missing marker fails closed rather than treating it as booked out.

## Step 3: Phone alerts
1. Install [ntfy](https://ntfy.sh/) on your iPhone or Android; allow mobile notifications.
2. Subscribe to a **random secret topic** of 24–120 letters/numbers/underscores/hyphens. Public ntfy topics are accessible to anyone who can guess a topic; do not send personal information.
3. GitHub repository > **Settings > Secrets and variables > Actions > New repository secret**.
4. Name: `NTFY_TOPIC`, value: exactly your random ntfy topic.
5. Actions > Run workflow > select **test-push**. A clearly labelled TEST ONLY notification should arrive; it is not real availability.

## Safety, reliability and cost
- Best-effort cron checks at minutes 02,07,12,... UTC. GitHub can delay or omit scheduled runs.
- A public repo's normal GitHub-hosted Actions minutes are free, but code, logs and uploaded diagnostic artifacts could be public. Never upload secrets.
- Scheduled runs exit quickly while monitoring is disabled or after 15 Dec. Disable the workflow manually after target dates.
- No account authentication, purchase, or CAPTCHA bypass.
- Local parsing tests: `python -m unittest discover -s tests -v`.

The previous ChatGPT hourly task is independent of this GitHub deployment.