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
- «Последние матчи» в карточке Counter-Strike 2 сначала просит у гостя код
  авторизации истории матчей и код матча. Код авторизации хранится в базе в
  зашифрованном виде, а новые матчи подхватываются по цепочке кодов Steam.
- Без `OPENDOTA_API_KEY` используется открытый лимит OpenDota. Ключ увеличивает
  лимит запросов и не передаётся в браузер.
- Если в Steam скрыты «Данные об играх», привязка остаётся активной, а модалка
  объясняет, почему часы недоступны.
- Таблицы `guest_steam_accounts`, `guest_cs2_match_access` и
  `guest_cs2_matches` сохраняются локально на stage и не копируются ежедневным
  зеркалированием production.

## Матчи Counter-Strike 2 на stage

Steam Web API выдаёт последовательность кодов матчей, но полную статистику
матча возвращает CS2 Game Coordinator. Для него используется отдельный
серверный Steam-аккаунт. Гостевой пароль и пароль серверного аккаунта приложение
не хранит.

1. Установить Node.js 18+ и зависимости локального bridge:

   ```bash
   cd /root/cm_stage/CM_V2/services/cs2_gc
   npm install --omit=dev
   ```

2. На отдельном Steam-аккаунте добавить бесплатную Counter-Strike 2 в
   библиотеку. Получить refresh token в интерактивном режиме:

   ```bash
   node create_refresh_token.js
   ```

   Скрипт попросит логин, скрыто введёт пароль и при необходимости запросит код
   Steam Guard. Полученную строку нельзя отправлять в чат или коммитить.

3. Создать общий секрет bridge и добавить настройки в
   `/root/cm_stage/CM_V2/.env`:

   ```bash
   CS2_SECRET="$(openssl rand -hex 32)"
   printf '\nCS2_GC_BRIDGE_URL=http://127.0.0.1:32173\nCS2_GC_BRIDGE_SECRET=%s\n' "$CS2_SECRET" >> .env
   ```

   Отдельно вставить выданную скриптом строку `CS2_GC_REFRESH_TOKEN=...`.

4. Установить Python-зависимости, применить миграцию и включить сервис:

   ```bash
   cd /root/cm_stage/CM_V2
   venv/bin/pip install -r requirements.txt
   venv/bin/python scripts/migrate.py
   install -m 0644 deploy/systemd/clubmodule-stage-cs2-gc.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now clubmodule-stage-cs2-gc.service
   systemctl restart clubmodule-stage.service
   curl -sS http://127.0.0.1:32173/health
   ```

   Готовый bridge отвечает `{"ok":true,"steam":true,"gc":true}`. Его порт
   слушает только `127.0.0.1` и не доступен из интернета.

Код матча действует как курсор: Steam Web API возвращает только следующий матч.
Чтобы при первом подключении увидеть до пяти игр, гостю нужно скопировать код
самого раннего из доступных последних пяти матчей. Если он укажет самый свежий
код, этот матч появится сразу, а следующие будут добавляться после новых игр.
