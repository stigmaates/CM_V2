'use strict';

const crypto = require('crypto');
const http = require('http');
const SteamUser = require('steam-user');
const GlobalOffensive = require('globaloffensive');
const {matchMetadataDiagnostic, normalizeMatch} = require('./normalizer');

const PORT = Number(process.env.CS2_GC_PORT || 32173);
const HOST = '127.0.0.1';
const SECRET = String(process.env.CS2_GC_BRIDGE_SECRET || '');
const REFRESH_TOKEN = String(process.env.CS2_GC_REFRESH_TOKEN || '');
const REQUEST_TIMEOUT_MS = 20000;

if (!SECRET || !REFRESH_TOKEN) {
  console.error('CS2_GC_BRIDGE_SECRET and CS2_GC_REFRESH_TOKEN are required');
  process.exit(1);
}

const steam = new SteamUser({renewRefreshTokens: false});
const cs2 = new GlobalOffensive(steam);
let ready = false;
let queue = Promise.resolve();
let reconnectTimer = null;
let shuttingDown = false;

function launchCS2Coordinator() {
  steam.gamesPlayed([730]);
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    if (!steam.steamID || cs2.haveGCSession) return;
    console.warn('CS2 Game Coordinator did not connect; restarting app session');
    steam.gamesPlayed([]);
    setTimeout(() => {
      if (steam.steamID && !cs2.haveGCSession) steam.gamesPlayed([730]);
    }, 1000);
  }, 15000);
}

function requestMatch(shareCode, steamId) {
  return new Promise((resolve, reject) => {
    if (!ready || !cs2.haveGCSession) {
      reject(new Error('Steam Game Coordinator ещё не готов'));
      return;
    }
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      cs2.removeListener('matchList', onMatchList);
      error ? reject(error) : resolve(value);
    };
    const onMatchList = (matches) => {
      if (!Array.isArray(matches) || !matches.length) {
        finish(new Error('Матч по этому коду не найден'));
        return;
      }
      try {
        const normalized = normalizeMatch(matches[0], steamId, shareCode);
        if (normalized.map_name === 'unknown' || normalized.mode_label === 'Официальный матч') {
          console.warn(`CS2 unresolved match metadata: ${JSON.stringify(matchMetadataDiagnostic(matches[0]))}`);
        }
        finish(null, normalized);
      } catch (error) {
        finish(error);
      }
    };
    const timeout = setTimeout(
      () => finish(new Error('Steam не ответил по матчу вовремя')),
      REQUEST_TIMEOUT_MS,
    );
    cs2.once('matchList', onMatchList);
    try {
      cs2.requestGame(shareCode);
    } catch (error) {
      finish(error);
    }
  });
}

function authorized(request) {
  const supplied = String(request.headers.authorization || '').replace(/^Bearer\s+/i, '');
  const expected = Buffer.from(SECRET);
  const actual = Buffer.from(supplied);
  return expected.length === actual.length && crypto.timingSafeEqual(expected, actual);
}

function respond(response, status, body) {
  response.writeHead(status, {'Content-Type': 'application/json; charset=utf-8'});
  response.end(JSON.stringify(body));
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    let raw = '';
    request.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 16384) request.destroy();
    });
    request.on('end', () => {
      try { resolve(JSON.parse(raw || '{}')); } catch (error) { reject(error); }
    });
    request.on('error', reject);
  });
}

const server = http.createServer(async (request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    respond(response, ready ? 200 : 503, {ok: ready, steam: Boolean(steam.steamID), gc: cs2.haveGCSession});
    return;
  }
  if (request.method !== 'POST' || request.url !== '/match') {
    respond(response, 404, {ok: false, error: 'not_found'});
    return;
  }
  if (!authorized(request)) {
    respond(response, 401, {ok: false, error: 'unauthorized'});
    return;
  }
  try {
    const body = await readJson(request);
    const shareCode = String(body.share_code || '').trim();
    const steamId = String(body.steam_id || '').trim();
    if (!/^CSGO-(?:[A-Za-z0-9]{5}-){4}[A-Za-z0-9]{5}$/.test(shareCode) || !/^\d{17}$/.test(steamId)) {
      respond(response, 400, {ok: false, error: 'invalid_input'});
      return;
    }
    const task = queue.then(() => requestMatch(shareCode, steamId));
    queue = task.catch(() => undefined);
    const match = await task;
    respond(response, 200, {ok: true, match});
  } catch (error) {
    console.error(`CS2 match request failed: ${error.message}`);
    respond(response, ready ? 422 : 503, {ok: false, error: ready ? 'match_unavailable' : 'gc_unavailable'});
  }
});

function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  ready = false;
  clearTimeout(reconnectTimer);
  console.log(`Received ${signal}; closing CS2 GC bridge`);
  try {
    steam.gamesPlayed([]);
    steam.logOff();
  } catch (error) {
    console.warn(`Steam shutdown warning: ${error.message}`);
  }
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000);
}

process.once('SIGTERM', () => shutdown('SIGTERM'));
process.once('SIGINT', () => shutdown('SIGINT'));

steam.on('loggedOn', () => {
  console.log('Steam connected; launching CS2 Game Coordinator session');
  steam.setPersona(SteamUser.EPersonaState.Invisible);
  launchCS2Coordinator();
  steam.requestFreeLicense([730], (error, grantedPackageIds, grantedAppIds) => {
    if (error) {
      console.warn(`Could not request the free CS2 license: ${error.message}`);
      return;
    }
    if ((grantedPackageIds || []).length || (grantedAppIds || []).length) {
      console.log('Free CS2 license granted to the service account');
    }
    if (!cs2.haveGCSession) launchCS2Coordinator();
  });
});
steam.on('error', (error) => {
  ready = false;
  console.error(`Steam connection error: ${error.message}`);
});
cs2.on('connectedToGC', () => {
  ready = true;
  clearTimeout(reconnectTimer);
  console.log('CS2 Game Coordinator connected');
});
cs2.on('disconnectedFromGC', () => {
  ready = false;
  console.warn('CS2 Game Coordinator disconnected');
  if (steam.steamID) launchCS2Coordinator();
});

server.listen(PORT, HOST, () => console.log(`CS2 GC bridge listening on ${HOST}:${PORT}`));
steam.logOn({refreshToken: REFRESH_TOKEN, machineName: 'Cyber Bonus CS2 bridge'});
