'use strict';

const ACCOUNT_ID_OFFSET = 76561197960265728n;

function pick(value, ...names) {
  if (!value) return undefined;
  for (const name of names) {
    if (value[name] !== undefined && value[name] !== null) return value[name];
  }
  return undefined;
}

function asNumber(value, fallback = 0) {
  if (value === undefined || value === null) return fallback;
  if (typeof value === 'object' && typeof value.toNumber === 'function') return value.toNumber();
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function asString(value) {
  if (value === undefined || value === null) return '';
  return typeof value === 'object' && typeof value.toString === 'function'
    ? value.toString()
    : String(value);
}

function extractMapName(...values) {
  for (const value of values) {
    const raw = asString(value).trim().toLowerCase();
    if (!raw) continue;
    const match = raw.match(/(?:^|[^a-z0-9])((?:de|cs|ar|dz)_[a-z0-9_]+)(?:$|[^a-z0-9_])/i);
    if (match) return match[1].toLowerCase();
  }
  return 'unknown';
}

function playerRankType(reservation, accountId, playerIndex) {
  const rankings = pick(reservation, 'rankings') || [];
  const ranking = rankings.find(
    (value) => asNumber(pick(value, 'account_id', 'accountId'), -1) === accountId,
  ) || rankings[playerIndex];
  return asNumber(pick(ranking, 'rank_type_id', 'rankTypeId'), -1);
}

function modeLabel({gameType, rankType, playerCount}) {
  const rankLabels = {
    6: 'Competitive',
    7: 'Wingman',
    10: 'Danger Zone',
    11: 'Premier',
    12: 'Competitive',
  };
  if (rankLabels[rankType]) return rankLabels[rankType];

  // Steam occasionally omits ranking metadata from match-history responses.
  // Official Wingman games always contain two teams of two players.
  if (playerCount === 4) return 'Wingman';

  const labels = {
    0: 'Casual',
    1: 'Competitive',
    2: 'Wingman',
    4: 'Arms Race',
    5: 'Demolition',
    6: 'Danger Zone',
    16: 'Deathmatch',
    32768: 'Premier',
  };
  return labels[gameType] || 'Официальный матч';
}

function normalizeMatch(match, steamId, shareCode) {
  const rounds = pick(match, 'roundstatsall', 'roundstatsAll') || [];
  if (!rounds.length) throw new Error('Steam вернул матч без итоговой статистики');
  const finalRound = rounds[rounds.length - 1];
  const reservation = pick(finalRound, 'reservation') || {};
  const accountIds = pick(reservation, 'account_ids', 'accountIds') || [];
  const accountId = Number(BigInt(steamId) - ACCOUNT_ID_OFFSET);
  const playerIndex = accountIds.findIndex((value) => asNumber(value, -1) === accountId);
  if (playerIndex < 0) throw new Error('Игрок не найден в переданном матче');

  const kills = pick(finalRound, 'kills') || [];
  const deaths = pick(finalRound, 'deaths') || [];
  const assists = pick(finalRound, 'assists') || [];
  const teamScores = pick(finalRound, 'team_scores', 'teamScores') || [];
  const teamIndex = playerIndex < Math.ceil(accountIds.length / 2) ? 0 : 1;
  const opponentIndex = teamIndex === 0 ? 1 : 0;
  const teamScore = teamScores[teamIndex] === undefined ? null : asNumber(teamScores[teamIndex]);
  const opponentScore = teamScores[opponentIndex] === undefined ? null : asNumber(teamScores[opponentIndex]);
  const won = teamScore === null || opponentScore === null || teamScore === opponentScore
    ? null
    : teamScore > opponentScore;
  const watchable = pick(match, 'watchablematchinfo', 'watchableMatchInfo') || {};
  const mapName = extractMapName(
    pick(watchable, 'game_map', 'gameMap'),
    pick(finalRound, 'map'),
    pick(watchable, 'game_mapgroup', 'gameMapgroup', 'gameMapGroup'),
  );
  const gameType = asNumber(
    pick(watchable, 'game_type', 'gameType') ?? pick(reservation, 'game_type', 'gameType'),
    -1,
  );
  const rankType = playerRankType(reservation, accountId, playerIndex);

  return {
    share_code: shareCode,
    match_id: asString(pick(match, 'matchid', 'matchId')),
    played_at: asNumber(pick(match, 'matchtime', 'matchTime')) || null,
    map_name: mapName,
    mode_label: modeLabel({gameType, rankType, playerCount: accountIds.length}),
    result_label: won === true ? 'Победа' : won === false ? 'Поражение' : 'Ничья',
    won,
    team_score: teamScore,
    opponent_score: opponentScore,
    duration_seconds: asNumber(pick(finalRound, 'match_duration', 'matchDuration')) || null,
    kills: kills[playerIndex] === undefined ? null : asNumber(kills[playerIndex]),
    deaths: deaths[playerIndex] === undefined ? null : asNumber(deaths[playerIndex]),
    assists: assists[playerIndex] === undefined ? null : asNumber(assists[playerIndex]),
  };
}

module.exports = {normalizeMatch};
