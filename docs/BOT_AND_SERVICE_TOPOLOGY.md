# Bot and service topology

Cyber Bonus uses two different Telegram bots. They must run as two different
systemd services because Telegram callbacks are delivered only to the bot that
sent the message.

## Telegram bots

| Env var | Service | Entrypoint | Purpose |
| --- | --- | --- | --- |
| `BOT_TOKEN` | `clubmodule-stage-bot.service` / `clubmodule-bot.service` | `python -m bot.main` | Guest login, guest bot flows, `/start`, contact sharing, guest-facing callbacks. |
| `CM_BONUS_BOT_TOKEN` | `clubmodule-stage-admin-bot.service` / `clubmodule-admin-bot.service` | `python -m bot.admin_main` | Admin chat buttons: prize issued, КБ credited. |

Do not run `bot.admin_main` instead of the guest bot service. That fixes admin
chat buttons but breaks guest login.

Do not run both services with the same token. Telegram long polling allows only
one active consumer per bot token.

## Stage services

| Unit | Purpose |
| --- | --- |
| `clubmodule-stage.service` | Stage web app. |
| `clubmodule-stage-bot.service` | Stage guest Telegram bot, uses `BOT_TOKEN`. |
| `clubmodule-stage-admin-bot.service` | Stage admin Telegram bot, uses `CM_BONUS_BOT_TOKEN`. |
| `clubmodule-stage-operational-alerts.timer` | Stage technical alerts schedule. |
| `clubmodule-stage-backup.timer` | Stage MySQL backup schedule. |

Install the stage admin bot:

```bash
cd /root/cm_stage/CM_V2
cp deploy/systemd/clubmodule-stage-admin-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now clubmodule-stage-admin-bot.service
systemctl status clubmodule-stage-admin-bot.service --no-pager -l
```

## Production services

| Unit | Purpose |
| --- | --- |
| `clubmodule.service` | Production web app. |
| `clubmodule-bot.service` | Production guest Telegram bot, uses `BOT_TOKEN`. |
| `clubmodule-admin-bot.service` | Production admin Telegram bot, uses `CM_BONUS_BOT_TOKEN`. |
| `clubmodule-operational-alerts.timer` | Production technical alerts schedule, if installed. |
| `clubmodule-backup.timer` | Production MySQL backup schedule. |

Install the production admin bot only during an approved production rollout:

```bash
cd /root/cm_v2/CM_V2
cp deploy/systemd/clubmodule-admin-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now clubmodule-admin-bot.service
systemctl status clubmodule-admin-bot.service --no-pager -l
```

## Admin dashboard restart allowlist

Stage `.env`:

```env
ADMIN_SERVICE_RESTART_ENABLED=true
ADMIN_RESTART_SERVICES=clubmodule-stage.service:Stage Web,clubmodule-stage-bot.service:Stage Guest Bot,clubmodule-stage-admin-bot.service:Stage Admin Bot,clubmodule-stage-operational-alerts.timer:Stage Alerts Timer
```

Production `.env`:

```env
ADMIN_SERVICE_RESTART_ENABLED=true
ADMIN_RESTART_SERVICES=clubmodule.service:Production Web,clubmodule-bot.service:Production Guest Bot,clubmodule-admin-bot.service:Production Admin Bot,clubmodule-operational-alerts.timer:Production Alerts Timer
```

If the web service runs as `www-data`, sudoers must allow exactly the same
unit names with `/usr/bin/systemctl --no-block restart ...`.

## Health checks

```bash
systemctl status clubmodule-stage.service --no-pager -l
systemctl status clubmodule-stage-bot.service --no-pager -l
systemctl status clubmodule-stage-admin-bot.service --no-pager -l
journalctl -u clubmodule-stage-bot.service -n 120 --no-pager
journalctl -u clubmodule-stage-admin-bot.service -n 120 --no-pager
```

Expected behavior:

- Guest login works only when the guest bot service is running.
- `Приз выдан` and `КБ зачислены` buttons work only when the admin bot service is running.
- Restart buttons appear in the admin dashboard only for units listed in
  `ADMIN_RESTART_SERVICES`.
