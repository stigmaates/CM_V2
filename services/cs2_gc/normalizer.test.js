'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {normalizeMatch} = require('./normalizer');

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
    mode_label: 'Соревновательный',
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
