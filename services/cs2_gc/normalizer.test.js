'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {matchMetadataDiagnostic, normalizeMatch} = require('./normalizer');

test('normalizes the linked player result from cumulative round stats', () => {
  const steamId = '76561198000000000';
  const accountId = Number(BigInt(steamId) - 76561197960265728n);
  const match = {
    matchid: '987654321',
    matchtime: 1789000000,
    roundstatsall: [{
      map: 'de_mirage',
      reservation: {
        account_ids: [accountId, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        game_type: 1,
      },
      team_scores: [13, 7],
      kills: [21, 1, 2, 3, 4, 5, 6, 7, 8, 9],
      deaths: [8, 1, 2, 3, 4, 5, 6, 7, 8, 9],
      assists: [4, 1, 2, 3, 4, 5, 6, 7, 8, 9],
      match_duration: 2165,
    }],
  };

  assert.deepEqual(normalizeMatch(match, steamId, 'CSGO-aaaaa-bbbbb-ccccc-ddddd-eeeee'), {
    share_code: 'CSGO-aaaaa-bbbbb-ccccc-ddddd-eeeee',
    match_id: '987654321',
    played_at: 1789000000,
    map_name: 'de_mirage',
    mode_label: 'Competitive',
    result_label: 'Победа',
    won: true,
    team_score: 13,
    opponent_score: 7,
    duration_seconds: 2165,
    kills: 21,
    deaths: 8,
    assists: 4,
  });
});

test('uses watchable map metadata instead of the demo URL and detects Wingman', () => {
  const steamId = '76561198000000000';
  const accountId = Number(BigInt(steamId) - 76561197960265728n);
  const match = {
    matchid: '987654322',
    matchtime: 1789000100,
    watchablematchinfo: {
      game_map: 'de_inferno',
      game_mapgroup: 'mg_de_inferno',
      game_type: 1048584,
    },
    roundstatsall: [{
      map: 'http://replay.example/730/987654322_123.dem.bz2',
      reservation: {
        account_ids: [accountId, 2, 3, 4],
        game_type: 1048584,
      },
      team_scores: [9, 7],
      kills: [12, 3, 10, 4],
      deaths: [10, 8, 12, 9],
      assists: [1, 2, 3, 4],
    }],
  };

  const result = normalizeMatch(match, steamId, 'CSGO-aaaaa-bbbbb-ccccc-ddddd-eeeee');

  assert.equal(result.map_name, 'de_inferno');
  assert.equal(result.mode_label, 'Wingman');
});

test('uses the linked player rank type to distinguish Premier', () => {
  const steamId = '76561198000000000';
  const accountId = Number(BigInt(steamId) - 76561197960265728n);
  const match = {
    roundstatsall: [{
      map: 'de_mirage',
      reservation: {
        account_ids: [accountId, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        rankings: [{account_id: accountId, rank_type_id: 11}],
      },
      team_scores: [13, 10],
      kills: [20],
      deaths: [14],
      assists: [5],
    }],
  };

  assert.equal(
    normalizeMatch(match, steamId, 'CSGO-aaaaa-bbbbb-ccccc-ddddd-eeeee').mode_label,
    'Premier',
  );
});

test('builds a serializable diagnostic for unresolved Steam metadata', () => {
  const diagnostic = matchMetadataDiagnostic({
    matchid: '987654323',
    roundstatsall: [{
      map: 'http://replay.example/730/987654323_123.dem.bz2',
      map_id: 42,
      max_rounds: 16,
      reservation: {
        account_ids: [1, 2, 0, 0],
        game_type: 1048584,
        rankings: [{rank_type_id: 7}],
      },
    }],
  });

  assert.equal(diagnostic.final_round.map_id, 42);
  assert.equal(diagnostic.final_round.account_count, 4);
  assert.equal(diagnostic.final_round.active_account_count, 2);
  assert.deepEqual(diagnostic.final_round.rank_types, [7]);
  assert.doesNotThrow(() => JSON.stringify(diagnostic));
});
