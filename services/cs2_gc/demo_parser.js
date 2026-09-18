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

async function loadDemoMetadata(rawUrl, dependencies = {}) {
  const download = dependencies.downloadAndDecompressDemo || downloadAndDecompressDemo;
  const parse = dependencies.parseDemoMetadata || parseDemoMetadata;
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), 'cyber-bonus-cs2-'));
  const demoPath = path.join(tempDirectory, 'match.dem');
  try {
    await download(rawUrl, demoPath);
    return parse(demoPath);
  } finally {
    await rm(tempDirectory, {recursive: true, force: true});
  }
}

function enrichMatchWithDemo(match, normalized, dependencies = {}) {
  const rawUrl = extractDemoUrl(match);
  if (!rawUrl) return Promise.resolve(normalized);
  return loadDemoMetadata(rawUrl, dependencies).then((metadata) => ({
    ...normalized,
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
  validateDemoUrl,
};
