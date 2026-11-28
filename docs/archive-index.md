# 아카이브 인덱스 — 2026-11-28

`~/.hermes/skills/.archive/` 에 남은 스킬의 이름·설명·사용 기록이다.
**디렉터리 내용은 tar로 백업했다**: `~/.hermes/state/slopgate/archive-backup-20261128.tar.gz` (9.5MB, 791개 확인).

## 왜 이 문서가 있나

아카이브는 git 저장소가 아니라 `~/.hermes/skills` 안에만 있고, 인덱스 비용은 **0**이다
(활성 스킬만 세므로). 그래서 급하지 않지만, 나중에 "그 스킬 있었는데"를 막으려면
**무엇이 들어 있었는지**가 남아야 한다. 내용은 tar에 있고, 여기에는 찾아보는 색인만 둔다.

## 복구 완료 (2026-11-28)

31개를 활성으로 되돌렸다. 근거 3가지:

1. **MEMORY.md/USER.md가 이름으로 참조** — 6개(`deploying-ai-scanner-honeypots`, `github-org-security-policies`, `hermes-agent-skill-authoring`, `korean-ai-support-programs`, `trusted-input-events`, `vm-obfuscated-binary-mapping`)가 아카이브 상태여서 `skill_view` 가 `not found` 를 돌려주고 있었다. 메모리가 지시하는 파일이 없는 상태였다.
2. **내가 만든 것(created_by=agent) 중 사용 기록이 있는 것** — 지식 자산이고, 실제로 열어본 기록이 곧 수요의 증거다.
3. **연쇄 참조** — 복구한 스킬이 `cloudflare-tunnel-service-exposure`(use=9)·`himalaya`(use=3)를 부르고 있어 같이 되돌렸다. 그 결과 깨진 참조 2건(`bugfix-repro-and-patch-hygiene.md`, `codex-timeout-recovery.md`)이 드러났는데, 둘 다 `coding-tool-orchestration/references/` 에 실재하는데도 상대경로 표기 때문에 못 찾고 있었다 — 경로를 명시해 고쳤다.

**인덱스 영향**: 25,505 → 28,150자 (예산 60,000). 스킬 277 → 308개.

## 사용 기록이 있는 나머지 (41개)

복구하지 않은 것들이다. 활성 스킬과 역할이 겹치거나(groups 참조), 지금 프로젝트에서 안 쓴다.

| 스킬 | 사용 | 마지막 | 설명 |
|---|---|---|---|
| `palworld-server` | 18 | 2026-08-07 | Run a Palworld dedicated server on macOS/Apple Silicon via Docker. Covers Docker setup, save migrati |
| `macos-app-install-and-setup` | 15 | 2026-10-10 | Use when installing or setting up macOS desktop apps. |
| `palworld-server-macos-managed` | 11 | 2026-07-29 | Run and manage a Palworld 1.0 dedicated server in Docker on macOS Apple Silicon — setup, config tuni |
| `github` | 10 | 2026-10-14 | GitHub via gh CLI: PRs, issues, reviews, repos, auth. |
| `macos-resource-audit-and-cleanup` | 9 | 2026-10-11 | Use when a Mac wastes disk, RAM, battery, or CPU. |
| `docker-game-server` | 7 | 2026-08-10 | Run SteamCMD-based game server Docker containers on macOS (Apple Silicon). Covers Palworld and simil |
| `palworld-dedicated-server-mac` | 7 | 2026-08-07 | Run a Palworld 1.0 dedicated server on macOS (Apple Silicon) with Docker Desktop. Covers setup, conf |
| `discord-gateway-reconnect-troubleshooting` | 6 | 2026-06-23 | Diagnose and fix Hermes Discord gateway reconnect failures, including zombie websocket states, privi |
| `codebase-inspection` | 5 | 2026-09-28 | Inspect codebases w/ pygount: LOC, languages, ratios. |
| `discord-gateway-operations` | 5 | 2026-08-01 | Set up, verify, and troubleshoot Hermes Discord gateway connectivity. |
| `frontend-accessibility-testing` | 5 | 2026-08-01 | Use when adding axe a11y tests to a vitest/jsdom suite. |
| `macos-license-integrity-analysis` | 5 | 2026-10-13 | Analyze a commercial macOS app's license/integrity checks. |
| `email-monitoring` | 4 | 2026-08-11 | Email arrival alerts: IMAP setup + new-mail watchdog cron. |
| `macos-sleep-and-keep-awake` | 4 | 2026-10-02 | Use when a Mac slept unexpectedly or must stay awake. |
| `gitleaks-false-positive-suppression` | 3 | 2026-08-06 | Suppress Gitleaks false positives with the narrowest possible scope. Covers the suppression progress |
| `strategy-extraction` | 3 | 2026-07-26 | Extract embedded decision/scheduling heuristics from execution code into injectable, testable strate |
| `vision-fallback` | 3 | 2026-08-20 | Extract text and data from images when the model lacks native vision — using EasyOCR for screenshots |
| `agent-persona-management` | 2 | 2026-08-01 | Use when changing agent voice or finding SOUL.md personas. |
| `css-design-token-migration` | 2 | 2026-06-27 | Systematic migration of CSS design tokens, palettes, borders, and component styles across multi-page |
| `obsidian` | 2 | 2026-07-16 | Read, search, create, and edit notes in the Obsidian vault. |
| `ollama-local-mac-deployment` | 2 | 2026-07-27 | Deploy Local LLMs using Ollama on Apple Silicon (M5), macOS brew service config (OLLAMA_ORIGINS), lo |
| `python-webserver-security` | 2 | 2026-08-04 | Harden Python stdlib HTTP servers (BaseHTTPRequestHandler) with rate limiting, security headers, and |
| `repo-cleanup` | 2 | 2026-09-25 | Systematically clean junk files (IDE configs, build artifacts, compiled binaries, macOS files, dupli |
| `test-fixture-date-safety` | 2 | 2026-08-10 | Use when migrating time-bomb test fixture dates. |
| `vanilla-js-web-pitfalls` | 2 | 2026-06-28 | Common pitfalls in vanilla JS multi-page web projects (no bundler, no framework) — defer script timi |
| `web-application-debugging` | 2 | 2026-07-22 | Debug web application integration issues — frontend-backend connectivity, auth flows, security verif |
| `auditing-unknown-source-trees` | 1 | 2026-09-28 | Use when auditing a leaked/decompiled source tree. |
| `authorized-web-vuln-assessment` | 1 | 2026-08-23 | Web vuln assessment: safe probing, repro reports, exploits. |
| `community-skill-install` | 1 | 2026-08-24 | Use when hermes skills install fails on a community repo. |
| `dogfood` | 1 | 2026-08-02 | Exploratory QA of web apps: find bugs, evidence, reports. |
| `dotnet-repo-review` | 1 | 2026-08-01 | Evaluate and harden .NET/C# repositories: full-repo quality review, macOS build verification, tests/ |
| `hearthstone-automation` | 1 | 2026-08-25 | Use when setting up the Hearthstone auto-play bot. |
| `llm-wiki` | 1 | 2026-06-23 | Karpathy's LLM Wiki: build/query interlinked markdown KB. |
| `opencode` | 1 | 2026-08-01 | Delegate coding to OpenCode CLI (features, PR review). |
| `p2p-transport-adapters` | 1 | 2026-07-16 | >- |
| `powershell-script-debugging` | 1 | 2026-08-21 | Debug PowerShell scripts: StrictMode .Count, parse pitfalls |
| `python-flask-webapp-security-assessment` | 1 | 2026-08-23 | Audit Flask/Werkzeug web apps for vulnerabilities. |
| `songsee` | 1 | 2026-08-08 | Audio spectrograms/features (mel, chroma, MFCC) via CLI. |
| `tailscale-diagnostics` | 1 | 2026-08-26 | Use when Tailscale peers look blocked or shields misleads. |
| `weekly-review-planning` | 1 | 2026-09-22 | Weekly reset: commitments, stalled work, next-week plan. |
| `xurl` | 1 | 2026-08-12 | X/Twitter via xurl CLI: raw post search, posting, DM, media. |

## 750개는 사용 기록이 0이다

`.archive/` 791개 중 **750개는 한 번도 열어본 적이 없다**(use_count·view_count 모두 0).
그중 703개는 2026-11-27 Q8 실행에서 인덱스에서 뺀 자동 설치 보안·포렌식 팩
(MIT 라이선스, `mukul975/Anthropic-Cybersecurity-Skills` 계열)이다. 나머지는 2026-09-23 이전 정리분.

**삭제하지 않고 tar로만 보관한다.** 이유:
- 되돌릴 수 없다 — `~/.hermes/skills` 는 git 저장소가 아니다
- 인덱스 비용이 0이라 남겨서 손해가 없다(디스크 29MB)
- 나중에 "그 스킬 있었는데"가 나오면 이 문서에서 이름을 찾고 tar에서 꺼내면 된다

복구하려면: `tar -xzf ~/.hermes/state/slopgate/archive-backup-20261128.tar.gz -C /tmp/ && mv /tmp/archive/<name> ~/.hermes/skills/`

## 이름 전체 목록

총 **750개**. 전체 이름은 `docs/archive-names.txt` 에 한 줄에 하나씩 있다 (같은 이유로 이 문서에 다 넣지 않았다 — 40k가 되면 아무도 안 읽는다).
