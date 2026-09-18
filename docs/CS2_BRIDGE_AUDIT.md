# CS2 bridge dependency audit

Audit performed on 2026-09-18 using Node.js 20.20.2 and npm 10.8.2. A clean
`npm ci --omit=dev` installation completed, all 10 bridge tests passed and
`npm audit --omit=dev --audit-level=low` reported **0 vulnerabilities**.

The original graph contained one critical vulnerability in `protobufjs` and
high-severity findings through `adm-zip`, `globaloffensive`, `steam-appticket`
and `steam-user`. They were removed without downgrading the Game Coordinator
libraries:

- `steam-appticket@1.0.2` is forced to the patched `protobufjs@7.6.6`;
- the unused Steam CDN ZIP extraction dependency is replaced by a local
  fail-closed `adm-zip` package;
- `steam-user@5.3.0` and `globaloffensive@3.3.0` remain pinned and were tested
  with the final dependency graph.

The ZIP replacement deliberately throws if Steam CDN ZIP extraction is ever
invoked. The bridge only uses Steam login and CS2 Game Coordinator match data,
so that path is outside its runtime flow. Failing closed prevents an unnoticed
return of the vulnerable extraction code.

## Release decision

The bridge dependency gate is complete. Production activation still requires
an isolated smoke test with a dedicated production technical Steam account,
fresh production-only secrets and `/health` returning
`{"ok":true,"steam":true,"gc":true}`. No stage refresh token may be reused.
