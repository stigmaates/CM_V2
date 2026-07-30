# Club onboarding runbook

Use this runbook when connecting a new club to ClubModule/Cyber Bonus.

The goal is to make each launch repeatable: no missing Telegram chat ids, no
unverified LANGAME sync, no owner account without smoke tests, and no launch
without a known rollback/support contact.

## Launch record

Fill this block before work starts.

| Field | Value |
| --- | --- |
| Club name | |
| Club ID | |
| Owner name/contact | |
| Launch date | |
| Support contact | |
| LANGAME access confirmed | yes / no |
| Telegram guest bot | |
| Telegram admin chat id for КБ | |
| Telegram admin chat id for tech alerts | |
| Stage smoke date | |
| Production deploy commit | |

## 1. Preflight

- Confirm the club uses LANGAME and API access is available.
- Confirm who owns the club settings after launch.
- Confirm Telegram bot strategy: shared guest bot or dedicated bot.
- Confirm where КБ/manual prize notifications should go.
- Confirm support channel and launch window.
- Confirm pilot success metrics: authorized guests, mission completions, spins, redemptions, repeat visits.
- Confirm privacy/terms expectations for guest data.

## 2. Technical setup

- Create or verify owner user.
- Create club record with the final `club_id`.
- Add club name, address/map/social links if available.
- Add LANGAME API key/secret.
- Add КБ/admin Telegram chat id.
- Add prize/admin notification chat id if separate.
- Check upload root and quota settings.
- Confirm the club is visible in admin dashboard.
- Confirm the owner can open owner dashboard.

## 3. Data sync

Run initial syncs for the new club.

```bash
cd /root/cm_stage/CM_V2
venv/bin/python scripts/sync_guests.py <CLUB_ID>
venv/bin/python scripts/sync_sessions_initial.py <CLUB_ID>
venv/bin/python scripts/sync_operations_initial.py <CLUB_ID>
venv/bin/python scripts/sync_balance_topups_initial.py --club-id <CLUB_ID>
```

Then check:

- guest count is plausible;
- sessions are present for the expected period;
- operations are present for the expected period;
- owner dashboard totals are plausible;
- CRM analytics open without errors;
- admin sync health for the club is green or has an understood reason.

## 4. Product configuration

- Configure case/wheel mode.
- Add at least one visible case or wheel prize if the launch includes game mechanics.
- Confirm prize probabilities are valid.
- Create launch missions or confirm missions are intentionally disabled.
- Configure token/КБ rules.
- Configure CM bonus redeem behavior.
- Configure first mailing segments if mailings are part of launch.
- Keep risky mass mailings disabled until guest flow is verified.

## 5. Guest smoke test

Use a safe test guest before public launch.

- Open guest login page.
- Start Telegram auth flow.
- Confirm Telegram login token resolves.
- Open guest dashboard.
- Confirm club identity is correct.
- Confirm token balance and КБ balance display.
- Complete or inspect missions.
- Spin/open case if enabled.
- Trigger КБ redeem test only if the admin chat is safe.
- Confirm Telegram admin notification arrives where expected.

## 6. Owner smoke test

- Owner login works.
- Owner dashboard opens.
- Cases/wheel page opens.
- Missions page opens.
- CRM page opens.
- Mailings page opens.
- Prize/КБ request views open.
- Settings page opens.
- Owner can understand the launch-state numbers.

## 7. Operational checks

Run from the target environment.

```bash
venv/bin/python scripts/check_environment.py --env-file .env
venv/bin/python scripts/migrate.py --dry-run
venv/bin/python scripts/check_background_jobs.py --max-running-minutes 60
venv/bin/python scripts/check_operational_alerts.py
venv/bin/python scripts/send_operational_alerts.py --dry-run
```

Confirm in admin dashboard:

- readiness block has no critical errors;
- backup is fresh;
- sync health for the club is acceptable;
- operational alerts are empty or understood;
- recent background jobs have no unexplained errors.

## 8. Launch decision

Launch only when all required items are true.

- Owner can log in.
- Guest Telegram login works.
- Initial guest/session/operation sync completed.
- Admin notification chat receives test notification.
- Backup monitor is green.
- No critical operational alerts.
- Support contact is ready.
- Rollback path is known.

If any item is false, do not launch publicly. Fix on stage or postpone launch.

## 9. First 24 hours

Check after launch:

- operational alerts;
- backup freshness;
- club sync health;
- guest Telegram authorization count;
- mission completions;
- spins/case openings;
- КБ redemptions;
- owner feedback;
- unexpected support requests.

## 10. Handoff

Send the owner:

- owner login URL;
- short explanation of dashboard metrics;
- how to check missions/cases/mailings;
- support contact;
- what not to change during the first day without support.

Record final launch notes:

- launch date/time;
- deployed commit;
- first backup path after launch;
- known issues;
- next follow-up date.
