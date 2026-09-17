# CS2 bridge dependency audit

Audit performed on 2026-09-18 using Node.js 20.20.2 and npm 10.8.2 against
the stage bridge manifest. A clean temporary `npm ci --omit=dev` installation
completed and all 11 bridge tests passed.

The candidate dependency graph is **not approved for production release**.
`npm audit --omit=dev` reported five vulnerabilities:

- one critical vulnerability in `protobufjs`;
- high vulnerabilities in `adm-zip`, `globaloffensive`, `steam-appticket` and
  `steam-user`.

The audit's only proposed remediation downgrades `steam-user` and
`globaloffensive` across major versions. That can break the Game Coordinator
protocol and is not an acceptable automatic production change.

`globaloffensive` 3.3.0 and `steam-user` 5.3.0 are currently the latest
published versions, so a normal compatible upgrade is not available.

## Release decision

Do not commit or deploy the CS2 bridge, its lock file, systemd unit, refresh
token or related migrations until one of these paths is completed:

1. replace or patch the vulnerable transitive dependencies and validate Steam
   Game Coordinator behaviour with a dedicated non-production account; or
2. choose a maintained match-data provider that does not require this bridge.

The Steam OpenID, public playtime and Dota/OpenDota package is independent of
the bridge and remains suitable for its own production release batch.
