# Steam-профиль гостя

Первый этап интеграции привязывает Steam-аккаунт к гостю через Steam OpenID и
показывает открытые часы в Counter-Strike 2 и Dota 2. Пароль Steam и персональный
API-ключ гостя приложение не получает и не хранит.

## Подготовка production

1. Зарегистрировать один серверный Web API key на
   `https://steamcommunity.com/dev/apikey` для публичного production-домена.
2. Добавить в production `.env`:

   ```dotenv
   STEAM_API_KEY=<server key>
   STEAM_PUBLIC_BASE_URL=https://<production-domain>
   ```

3. До выпуска проверить на копии production базы миграцию
   `0036_guest_steam_accounts`, затем применить её штатным механизмом миграций.
4. Убедиться, что production origin доступен извне по HTTPS: Steam вернёт
   пользователя именно на `STEAM_PUBLIC_BASE_URL/guest/steam/callback`.

## Поведение

- `/guest/steam/link` отправляет вошедшего гостя на официальный экран Steam.
- Callback проверяет подписанный OpenID-ответ у Steam и сохраняет SteamID64.
- Один SteamID нельзя привязать к двум гостям одного клуба.
- «Мой игровой профиль» загружает ник и часы только при открытии модалки.
- «Последние матчи» в карточке Dota 2 загружает пять последних доступных матчей
  из OpenDota. SteamID64 переводится в Steam32 только на сервере.
- История Dota 2 использует бесплатный публичный API OpenDota без отдельного
  ключа. Если сервис временно ограничит запросы или матчей нет в открытой
  истории, интерфейс сообщит об этом гостю.
- «Последние матчи» в карточке Counter-Strike 2 просит код авторизации истории
  матчей и код матча. Код авторизации хранится в зашифрованном виде, новые
  матчи подхватываются по цепочке кодов Steam.
- Карту и доступный тип матча CS2 bridge извлекает из демки Valve. Демка
  скачивается во временный каталог, после разбора удаляется, а результат
  сохраняется в `guest_cs2_matches`.
- При первой загрузке браузер запрашивает до пяти матчей по одному и показывает
  фактический прогресс после завершения каждого шага.
- Если в Steam скрыты «Данные об играх», привязка остаётся активной, а модалка
  объясняет, почему часы недоступны.
- Таблицы `guest_steam_accounts`, `guest_cs2_match_access` и
  `guest_cs2_matches` хранятся в production базе и относятся к конкретному
  клубу и гостю.

## Матчи Counter-Strike 2 в production

Steam Web API выдаёт последовательность кодов матчей, но полную статистику
матча возвращает CS2 Game Coordinator. Для него используется отдельный
серверный Steam-аккаунт. Гостевой пароль и пароль серверного аккаунта приложение
не хранит.

1. Использовать Node.js 18+ и установить зависимости строго по lock-файлу
   через npm 10.8.2 (системный npm 9 на production-хосте этот lock-файл не
   устанавливает):

   ```bash
   cd /root/cm_v2/CM_V2/services/cs2_gc
   npx --yes npm@10.8.2 ci --omit=dev --no-audit --no-fund
   npm test
   python3 ../../scripts/check_cs2_bridge_release.py
   ```

2. На отдельном Steam-аккаунте добавить бесплатную Counter-Strike 2 в
   библиотеку. Получить refresh token в интерактивном режиме:

   ```bash
   node create_refresh_token.js
   ```

   Скрипт попросит логин, скрыто введёт пароль и при необходимости запросит код
   Steam Guard. Полученную строку нельзя отправлять в чат или коммитить.

3. Создать новый production-секрет bridge и добавить настройки в production
   `.env`. Stage-секрет и stage refresh token повторно не используются:

   ```dotenv
   CS2_GC_BRIDGE_URL=http://127.0.0.1:32174
   CS2_GC_BRIDGE_SECRET=<new production secret>
   CS2_GC_REFRESH_TOKEN=<new production refresh token>
   CS2_GC_PORT=32174
   ```

4. Установить Python-зависимости, отрепетировать миграцию
   `0037_guest_cs2_matches`, установить production unit выключенным и запустить
   его только для smoke-проверки:

   ```bash
   cd /root/cm_v2/CM_V2
   venv/bin/pip install -r requirements.txt
   venv/bin/python scripts/migrate.py --dry-run
   install -m 0644 deploy/systemd/clubmodule-cs2-gc.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl start clubmodule-cs2-gc.service
   curl -sS http://127.0.0.1:32174/health
   ```

   Готовый bridge отвечает `{"ok":true,"steam":true,"gc":true}`. Его порт
   слушает только `127.0.0.1` и не доступен из интернета.

Код матча действует как курсор: Steam Web API возвращает только следующий матч.
Чтобы при первом подключении увидеть до пяти игр, гостю нужно скопировать код
самого раннего из доступных последних пяти матчей. Если он укажет самый свежий
код, этот матч появится сразу, а следующие будут добавляться после новых игр.
