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
- Если в Steam скрыты «Данные об играх», привязка остаётся активной, а модалка
  объясняет, почему часы недоступны.
- Таблица `guest_steam_accounts` хранится в production базе и относится к
  конкретному клубу и гостю.
