# Steam-профиль гостя

Первый этап интеграции привязывает Steam-аккаунт к гостю через Steam OpenID и
показывает открытые часы в Counter-Strike 2 и Dota 2. Пароль Steam и персональный
API-ключ гостя приложение не получает и не хранит.

## Настройка stage

1. Зарегистрировать один серверный Web API key на
   `https://steamcommunity.com/dev/apikey` для публичного домена stage.
2. Добавить в `/root/cm_stage/CM_V2/.env`:

   ```dotenv
   STEAM_API_KEY=<server key>
   STEAM_PUBLIC_BASE_URL=https://stage.cyber-bonus.ru
   # Необязательно на stage; рекомендуется перед запуском на production.
   OPENDOTA_API_KEY=<OpenDota API key>
   ```

3. Обновить код, применить миграцию и перезапустить web:

   ```bash
   cd /root/cm_stage/CM_V2
   git pull --ff-only origin product-readiness-from-stage
   venv/bin/python scripts/migrate.py
   systemctl restart clubmodule-stage.service
   systemctl is-active clubmodule-stage.service
   ```

## Поведение

- `/guest/steam/link` отправляет вошедшего гостя на официальный экран Steam.
- Callback проверяет подписанный OpenID-ответ у Steam и сохраняет SteamID64.
- Один SteamID нельзя привязать к двум гостям одного клуба.
- «Мой игровой профиль» загружает ник и часы только при открытии модалки.
- «Последние матчи» в карточке Dota 2 загружает пять последних доступных матчей
  из OpenDota. SteamID64 переводится в Steam32 только на сервере.
- Без `OPENDOTA_API_KEY` используется открытый лимит OpenDota. Ключ увеличивает
  лимит запросов и не передаётся в браузер.
- Если в Steam скрыты «Данные об играх», привязка остаётся активной, а модалка
  объясняет, почему часы недоступны.
- Таблица `guest_steam_accounts` сохраняется локально на stage и не копируется
  ежедневным зеркалированием production.
