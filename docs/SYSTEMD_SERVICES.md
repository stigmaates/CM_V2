# systemd service templates

Templates live in `deploy/systemd/`.

They are intentionally conservative examples. Before installing them, adjust:

- `WorkingDirectory`
- `EnvironmentFile`
- `User`
- `Group`
- gunicorn bind address and worker count
- timer intervals

## Services

- `cyber-bonus-web.service` — web app through gunicorn.
- `cyber-bonus-guest-bot.service` — guest Telegram bot.
- `cyber-bonus-admin-bot.service` — admin/worker Telegram bot.
- `cyber-bonus-mailings.service` + `.timer` — queued mailings.
- `cyber-bonus-auto-mailings.service` + `.timer` — auto-mailings.
- `cyber-bonus-referrals.service` + `.timer` — referral rewards.

## Install example

```bash
sudo cp deploy/systemd/cyber-bonus-*.service /etc/systemd/system/
sudo cp deploy/systemd/cyber-bonus-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cyber-bonus-web.service
sudo systemctl enable --now cyber-bonus-guest-bot.service
sudo systemctl enable --now cyber-bonus-admin-bot.service
sudo systemctl enable --now cyber-bonus-mailings.timer
sudo systemctl enable --now cyber-bonus-auto-mailings.timer
sudo systemctl enable --now cyber-bonus-referrals.timer
```

## Check status

```bash
systemctl status cyber-bonus-web.service
systemctl status cyber-bonus-guest-bot.service
systemctl status cyber-bonus-admin-bot.service
systemctl list-timers 'cyber-bonus-*'
```

## Logs

```bash
journalctl -u cyber-bonus-web.service -n 100 --no-pager
journalctl -u cyber-bonus-guest-bot.service -n 100 --no-pager
journalctl -u cyber-bonus-admin-bot.service -n 100 --no-pager
```
