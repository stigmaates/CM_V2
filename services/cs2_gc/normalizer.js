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

function modeLabel(gameType) {
  const labels = {
    0: 'Обычный',
    1: 'Соревновательный',
    2: 'Напарники',
    4: 'Гонка вооружений',
    5: 'Уничтожение объекта',
    6: 'Запретная зона',
    16: 'Бой насмерть',
    32768: 'Премьер',
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
  const rawMap = String(pick(finalRound, 'map') || pick(watchable, 'game_map', 'gameMap') || '');
  const mapName = rawMap.match(/[a-z0-9_]+/i)?.[0] || 'unknown';
  const gameType = asNumber(pick(reservation, 'game_type', 'gameType'), -1);

  return {
    share_code: shareCode,
    match_id: asString(pick(match, 'matchid', 'matchId')),
    played_at: asNumber(pick(match, 'matchtime', 'matchTime')) || null,
    map_name: mapName,
    mode_label: modeLabel(gameType),
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
