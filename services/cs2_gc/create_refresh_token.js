'use strict';

const readline = require('readline');
const SteamUser = require('steam-user');

function prompt(question, {hidden = false} = {}) {
  if (!hidden || !process.stdin.isTTY) {
    const rl = readline.createInterface({input: process.stdin, output: process.stdout});
    return new Promise((resolve) => rl.question(question, (answer) => { rl.close(); resolve(answer.trim()); }));
  }
  return new Promise((resolve) => {
    let value = '';
    process.stdout.write(question);
    process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.setEncoding('utf8');
    const onData = (char) => {
      if (char === '\u0003') process.exit(130);
      if (char === '\r' || char === '\n') {
        process.stdin.setRawMode(false);
        process.stdin.pause();
        process.stdin.removeListener('data', onData);
        process.stdout.write('\n');
        resolve(value);
      } else if (char === '\u007f') {
        if (value) { value = value.slice(0, -1); process.stdout.write('\b \b'); }
      } else {
        value += char;
        process.stdout.write('*');
      }
    };
    process.stdin.on('data', onData);
  });
}

(async () => {
  const accountName = await prompt('Логин отдельного Steam-аккаунта: ');
  const password = await prompt('Пароль (не отображается): ', {hidden: true});
  const steam = new SteamUser({renewRefreshTokens: false});
  let tokenPrinted = false;
  steam.on('steamGuard', async (_domain, callback, lastCodeWrong) => {
    const code = await prompt(lastCodeWrong ? 'Код не подошёл. Новый код Steam Guard: ' : 'Код Steam Guard: ');
    callback(code);
  });
  steam.on('refreshToken', (token) => {
    tokenPrinted = true;
    console.log('\nСохраните эту строку в .env и никому не отправляйте:');
    console.log(`CS2_GC_REFRESH_TOKEN=${token}`);
  });
  steam.on('loggedOn', () => {
    if (!tokenPrinted) console.log('Вход выполнен; ожидаем новый refresh token…');
    setTimeout(() => { steam.logOff(); process.exit(tokenPrinted ? 0 : 1); }, 1500);
  });
  steam.on('error', (error) => { console.error(`Ошибка Steam: ${error.message}`); process.exit(1); });
  steam.logOn({accountName, password, machineName: 'Cyber Bonus CS2 bridge setup'});
})();
