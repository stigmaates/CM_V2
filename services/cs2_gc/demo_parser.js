'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {mkdtemp, rm} = require('node:fs/promises');
const {Readable, Transform} = require('node:stream');
const {pipeline} = require('node:stream/promises');
const demoParser = require('@laihoe/demoparser2');
const unbzip2 = require('unbzip2-stream');
const {extractDemoUrl, extractMapName, rankTypeModeLabel} = require('./normalizer');

const DOWNLOAD_TIMEOUT_MS = Number(process.env.CS2_DEMO_DOWNLOAD_TIMEOUT_MS || 60000);
const MAX_COMPRESSED_BYTES = Number(process.env.CS2_DEMO_MAX_COMPRESSED_BYTES || 256 * 1024 * 1024);
const MAX_DECOMPRESSED_BYTES = Number(process.env.CS2_DEMO_MAX_DECOMPRESSED_BYTES || 1024 * 1024 * 1024);
const GENERIC_MODE_LABEL = 'Официальный матч';

function byteLimit(maxBytes, label) {
  let total = 0;
  return new Transform({
    transform(chunk, encoding, callback) {
      total += chunk.length;
      if (total > maxBytes) {
        callback(new Error(`${label} превышает допустимый размер`));
        return;
      }
      callback(null, chunk);
    },
  });
}

function validateDemoUrl(rawUrl) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch (error) {
    throw new Error('Steam вернул некорректную ссылку на демо');
  }
  const hostname = url.hostname.toLowerCase();
  const allowedHost = hostname.endsWith('.valve.net') || hostname.endsWith('.steamcontent.com');
  if (!['http:', 'https:'].includes(url.protocol) || !allowedHost) {
    throw new Error('Steam вернул неподдерживаемую ссылку на демо');
  }
  return url;
}

async function downloadAndDecompressDemo(rawUrl, outputPath, fetchImpl = fetch) {
  const url = validateDemoUrl(rawUrl);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS);
  try {
    const response = await fetchImpl(url, {signal: controller.signal});
    if (!response.ok || !response.body) {
      throw new Error(`Steam не отдал демо: HTTP ${response.status}`);
    }
    const contentLength = Number(response.headers.get('content-length') || 0);
    if (contentLength > MAX_COMPRESSED_BYTES) {
      throw new Error('Сжатая демка превышает допустимый размер');
    }
    await pipeline(
      Readable.fromWeb(response.body),
      byteLimit(MAX_COMPRESSED_BYTES, 'Сжатая демка'),
      unbzip2(),
      byteLimit(MAX_DECOMPRESSED_BYTES, 'Распакованная демка'),
      fs.createWriteStream(outputPath, {flags: 'wx'}),
    );
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new Error('Steam не успел отдать демо вовремя');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function rows(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }
  return [];
}

function modeFromDemo(filePath, parser = demoParser) {
  try {
    const events = rows(parser.parseEvent(
      filePath,
      'player_spawn',
      ['comp_rank_type'],
    ));
    for (const event of events) {
      const rankType = Number(
        event.user_comp_rank_type ?? event.comp_rank_type ?? event.player_comp_rank_type,
      );
      if (!Number.isFinite(rankType)) continue;
      const label = rankTypeModeLabel(rankType);
      if (label !== GENERIC_MODE_LABEL) return label;
    }
  } catch (error) {
    // Map parsing is useful on its own; old/new CS2 patches can temporarily break event parsing.
  }
  return '';
}

function parseDemoMetadata(filePath, parser = demoParser) {
  const header = parser.parseHeader(filePath) || {};
  const mapName = extractMapName(header.map_name, header.mapName);
  if (mapName === 'unknown') throw new Error('В заголовке демо не найдена карта');
  return {
    map_name: mapName,
    mode_label: modeFromDemo(filePath, parser),
  };
}

function sameSteamId(value, steamId) {
  return String(value ?? '').replace(/\.0$/, '') === String(steamId || '');
}

function normalizeWeapon(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/^weapon_/, '')
    .replace(/[^a-z0-9_]/g, '');
}

function parseDemoPlayerStats(filePath, steamId, parser = demoParser) {
  if (!steamId) return {};
  const result = {};
  try {
    const deaths = rows(parser.parseEvent(filePath, 'player_death', [], []));
    let kills = 0;
    let assists = 0;
    let headshots = 0;
    const weaponKills = {};
    let foundPlayer = false;
    for (const event of deaths) {
      const attacker = event.attacker_steamid ?? event.attackerSteamid;
      const victim = event.userid_steamid ?? event.user_steamid ?? event.useridSteamid;
      const assister = event.assister_steamid ?? event.assisterSteamid;
      if (sameSteamId(attacker, steamId) || sameSteamId(victim, steamId) || sameSteamId(assister, steamId)) {
        foundPlayer = true;
      }
      if (sameSteamId(attacker, steamId) && !sameSteamId(victim, steamId)) {
        kills += 1;
        if (Boolean(event.headshot)) headshots += 1;
        const weapon = normalizeWeapon(event.weapon);
        if (weapon) weaponKills[weapon] = (weaponKills[weapon] || 0) + 1;
      }
      if (sameSteamId(assister, steamId)) assists += 1;
    }
    if (foundPlayer) {
      result.kills = kills;
      result.assists = assists;
      result.headshots = headshots;
      result.weapon_kills = weaponKills;
    }
  } catch (error) {
    // GC totals remain available when a new demo patch changes event fields.
  }
  try {
    const mvps = rows(parser.parseEvent(filePath, 'round_mvp', [], []));
    const hasSteamIds = mvps.some((event) => (
      event.userid_steamid ?? event.user_steamid ?? event.useridSteamid
    ) !== undefined);
    const mvp = mvps.filter((event) => sameSteamId(
      event.userid_steamid ?? event.user_steamid ?? event.useridSteamid,
      steamId,
    )).length;
    if (hasSteamIds) result.mvp = mvp;
  } catch (error) {
    // MVP is optional; other parsed metrics should still be returned.
  }
  return result;
}

async function loadDemoMetadata(rawUrl, dependencies = {}) {
  const download = dependencies.downloadAndDecompressDemo || downloadAndDecompressDemo;
  const parse = dependencies.parseDemoMetadata || parseDemoMetadata;
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), 'cyber-bonus-cs2-'));
  const demoPath = path.join(tempDirectory, 'match.dem');
  try {
    await download(rawUrl, demoPath);
    return parse(demoPath, dependencies.parser || demoParser, dependencies.steamId);
  } finally {
    await rm(tempDirectory, {recursive: true, force: true});
  }
}

function enrichMatchWithDemo(match, normalized, dependencies = {}) {
  const rawUrl = extractDemoUrl(match);
  if (!rawUrl) return Promise.resolve(normalized);
  return loadDemoMetadata(rawUrl, {
    ...dependencies,
    parseDemoMetadata: dependencies.parseDemoMetadata || ((filePath, parser, steamId) => ({
      ...parseDemoMetadata(filePath, parser),
      ...parseDemoPlayerStats(filePath, steamId, parser),
    })),
  }).then((metadata) => ({
    ...normalized,
    ...metadata,
    map_name: metadata.map_name || normalized.map_name,
    mode_label: metadata.mode_label || normalized.mode_label,
  }));
}

module.exports = {
  downloadAndDecompressDemo,
  enrichMatchWithDemo,
  loadDemoMetadata,
  modeFromDemo,
  parseDemoMetadata,
  parseDemoPlayerStats,
  validateDemoUrl,
};
