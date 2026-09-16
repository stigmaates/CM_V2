'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  downloadAndDecompressDemo,
  enrichMatchWithDemo,
  loadDemoMetadata,
  modeFromDemo,
  parseDemoMetadata,
  parseDemoPlayerStats,
  validateDemoUrl,
} = require('./demo_parser');

test('downloads and decompresses a Valve demo response', async () => {
  const compressed = Buffer.from(
    'QlpoOTFBWSZTWVUKL+MAAARfgEAAAAIQABYCSAAuY4wgIAAxQNNDIyYhEaAZNGmIPjIsZ0Zui8AVqCwzE9o+LuSKcKEgqhRfxg==',
    'base64',
  );
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'cyber-bonus-cs2-test-'));
  const outputPath = path.join(directory, 'match.dem');
  try {
    await downloadAndDecompressDemo(
      'http://replay123.valve.net/730/match.dem.bz2',
      outputPath,
      async () => new Response(compressed, {
        status: 200,
        headers: {'content-length': String(compressed.length)},
      }),
    );
    assert.equal(fs.readFileSync(outputPath).toString(), 'PBDEMS2\0synthetic-demo-data');
  } finally {
    fs.rmSync(directory, {recursive: true, force: true});
  }
});

test('counts CS2 contract facts for the linked Steam player', () => {
  const steamId = '76561198000000001';
  const parser = {
    parseEvent: (filePath, eventName) => eventName === 'player_death' ? [
      {attacker_steamid: steamId, userid_steamid: '76561198000000002', weapon: 'weapon_ak47', headshot: true},
      {attacker_steamid: steamId, userid_steamid: '76561198000000003', weapon: 'awp', headshot: false},
      {attacker_steamid: '76561198000000004', userid_steamid: steamId, assister_steamid: '76561198000000005'},
      {attacker_steamid: '76561198000000004', userid_steamid: '76561198000000005', assister_steamid: steamId},
    ] : [
      {userid_steamid: steamId},
      {userid_steamid: '76561198000000002'},
    ],
  };

  assert.deepEqual(parseDemoPlayerStats('/tmp/match.dem', steamId, parser), {
    kills: 2,
    assists: 1,
    headshots: 1,
    weapon_kills: {ak47: 1, awp: 1},
    mvp: 1,
  });
});

test('accepts only Valve and Steam content demo URLs', () => {
  assert.equal(
    validateDemoUrl('http://replay123.valve.net/730/match.dem.bz2').hostname,
    'replay123.valve.net',
  );
  assert.equal(
    validateDemoUrl('https://cdn.steamcontent.com/730/match.dem.bz2').hostname,
    'cdn.steamcontent.com',
  );
  assert.throws(() => validateDemoUrl('http://127.0.0.1/private'));
  assert.throws(() => validateDemoUrl('https://example.com/match.dem.bz2'));
});

test('reads map and rank type from parsed demo data', () => {
  const parser = {
    parseHeader: () => ({map_name: 'de_inferno'}),
    parseEvent: () => [{user_comp_rank_type: 7}],
  };

  assert.deepEqual(parseDemoMetadata('/tmp/match.dem', parser), {
    map_name: 'de_inferno',
    mode_label: 'Wingman',
  });
  assert.equal(modeFromDemo('/tmp/match.dem', parser), 'Wingman');
});

test('keeps map metadata when event parsing is unavailable', () => {
  const parser = {
    parseHeader: () => ({map_name: 'de_ancient'}),
    parseEvent: () => { throw new Error('unsupported demo patch'); },
  };

  assert.deepEqual(parseDemoMetadata('/tmp/match.dem', parser), {
    map_name: 'de_ancient',
    mode_label: '',
  });
});

test('downloads to a temporary file, parses it and removes it', async () => {
  let downloadedPath;
  const result = await loadDemoMetadata(
    'http://replay123.valve.net/730/match.dem.bz2',
    {
      downloadAndDecompressDemo: async (url, outputPath) => {
        downloadedPath = outputPath;
        fs.writeFileSync(outputPath, 'demo');
      },
      parseDemoMetadata: (filePath) => {
        assert.equal(filePath, downloadedPath);
        assert.equal(fs.readFileSync(filePath, 'utf8'), 'demo');
        return {map_name: 'de_nuke', mode_label: 'Premier'};
      },
    },
  );

  assert.deepEqual(result, {map_name: 'de_nuke', mode_label: 'Premier'});
  assert.equal(fs.existsSync(downloadedPath), false);
});

test('enriches normalized GC statistics without replacing them', async () => {
  const normalized = {
    match_id: '42',
    map_name: 'unknown',
    mode_label: 'Официальный матч',
    kills: 12,
  };
  const source = {
    roundstatsall: [{map: 'http://replay123.valve.net/730/match.dem.bz2'}],
  };
  const enriched = await enrichMatchWithDemo(source, normalized, {
    downloadAndDecompressDemo: async (url, outputPath) => fs.writeFileSync(outputPath, 'demo'),
    parseDemoMetadata: () => ({map_name: 'de_vertigo', mode_label: 'Competitive'}),
  });

  assert.deepEqual(enriched, {
    match_id: '42',
    map_name: 'de_vertigo',
    mode_label: 'Competitive',
    kills: 12,
  });
});
