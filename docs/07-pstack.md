# pstack에서 가져올 것 / 못 가져올 것

강연의 실제 산출물은 **pstack**이다. Cursor 플러그인으로 배포되는 스킬·플레이북 묶음(스킬 62개, 그중 24개가 원칙).
출처: <https://github.com/cursor/plugins/tree/main/pstack> · MIT (© 2026 Lauren Tan) · 가이드: `docs/guide/01~10`

## 먼저: 플러그인으로는 못 쓴다

pstack은 Cursor 플러그인이다. `Task` 서브에이전트, `Projects`, `create-skill` 내장 플로우, 역할별 모델 라우팅
(`~/.cursor/rules/pstack-models.mdc`), `.cursor/skills/` 경로에 의존한다. Hermes에는 이 중 어느 것도 없다.
그래서 "설치"가 아니라 **이식(port)** 이다. 아래 표가 그 이식 목록이다.

## 가져올 것 (개념 → Hermes 대응물)

| pstack | 원문 요지 | slopgate 대응 | 우선순위 |
|---|---|---|---|
| `/correct` 래더 | 교정은 ①구조로 불가능하게 ②타입·린트·CI ③테스트 ④문서·규칙 순으로 시도. **문서/규칙이 마지막** | `templates/correction-to-gate.md`의 판정 순서를 이 래더로 교체. 지금은 "산문이냐 검사냐" 2지선다인데, 4단계로 쪼개야 정직하다 | **1** |
| `Encode Lessons in Structure` | 같은 조언을 두 번 하면 린트·체크·스크립트로 바꾼다 | 이 저장소의 존재 이유와 동일. `docs/01-model.md`의 변환 사례 표가 이미 그 형태 | 완료 |
| 24개 원칙 이름 (steering vocabulary) | 원칙을 매번 설명하지 않고 **이름으로 지시**한다. 에이전트는 적용한 원칙과 그것이 바꾼 결정을 답에 적는다 | 원칙 24개를 스킬 24개로 만들면 인덱스 비용이 폭증한다(현재 118k자 예산 초과 상태). 대신 **참조 문서 1개 + 스킬 1개**로 두고 대화에서 이름으로 지시 | 2 |
| `show-me-your-work` | 긴/무인 작업에서 결정을 TSV 로그로 남긴다 | 무인 크론(4단계 야간 팩토리)의 결정 로그 형식으로 채택. 산출물: `~/.hermes/state/slopgate/decisions.tsv` | 3 |
| `benchmark-checklist` (Explain the Number) | 숫자를 인용하기 전에 "무엇이 그 숫자를 제한하는가"를 7문항으로 확인 | `docs/05-metrics.md`에 이미 "왜 이 숫자를 신뢰하는가"를 적고 있음. 7문항을 그대로 붙인다 | 3 |
| `no-comments` / `unslop` / `deslop` | 주석은 탈출구, 산문은 AI 티를 지운다 | 새 레포 `AGENTS.md` 템플릿에 반영(소급 금지). 답변 문체도 동일 규칙 적용 | 3 |
| `statechart` | 사용자 관점 상태 머신을 그려 리뷰한다 | 웹/백엔드 흐름 리뷰(ASL·릴레이)에 유용. 필요할 때만 | 4 |
| `create-verification-skill` | 앱을 실제로 구동해 동작을 증명하는 스킬을 만드는 절차 | 브라우저 자동화 검증(browser-testing-with-devtools 계열)에 이미 부분 적용 | 4 |
| `reflect` | 한 세션에서 얻은 교훈을 Accepted/Rejected/Backlog로 나눠 승인 후 반영 | 이 저장소의 `docs/06-open-questions.md` + 스킬 갱신 흐름과 동일. 절차만 맞추면 됨 | 3 |

## 못 가져올 것

| pstack 기능 | 이유 | 대안 |
|---|---|---|
| `Task` 서브에이전트 + `poteto-agent` | Hermes의 `delegate_task`는 병렬 1개 제한이고 서브에이전트가 스킬을 공유하지 않는다 | `delegate_task` 1개 + 메인에서 검증 |
| `Projects`, `automations`, 클라우드 에이전트 팬아웃 | Cursor 전용 오케스트레이션 | 크론(`no_agent` 게이트) + PR 흐름 |
| 역할별 모델 라우팅 rules 파일 | Hermes는 `config.yaml`에서 aux 역할별 모델을 따로 잡는다 | `delegation.model`, aux 라우팅 설정 |
| `/swarm`, `/arena`, `/interrogate` | 다중 에이전트 패널 전제 | 설계 쟁점은 Codex/Claude 교차 검토 1회로 대체 |
| `create-skill` 내장 플로우 | Hermes는 `skill_manage` + 자체 린트 | `gates/skill_lint.py`가 그 역할의 일부를 이미 한다 |
| Cursor 규칙 파일(`.cursor/rules/*.mdc`) | 대상 런타임이 다름 | `AGENTS.md` + 스킬 |

## 원칙 24개를 어떻게 둘 것인가 (결정 필요)

- **A안**: 스킬 1개(`poteto-principles`)에 24개 요약 + 각 원칙의 트리거 문장. 인덱스 +1개. 이름으로 지시 가능.
- **B안**: 24개 원칙을 각각 스킬로. 선택 정확도는 높지만 인덱스 +24개, 지금 예산 초과 상태에서 역행.
- **내 의견**: A안. 이유는 `docs/05-metrics.md`의 인덱스 비용 때문이고, 원칙은 "매번 로드되는 지식"이 아니라 "이름으로 소환되는 어휘"라 한 문서로 충분하다.

## 이 문서 이후 할 일 (백로그)

1. `templates/correction-to-gate.md`를 `/correct` 4단계 래더로 재작성 (지금은 2지선다)
2. `poteto-principles` 스킬 초안 (A안) — 24개 이름 + 한 줄 규칙 + 트리거
3. 무인 작업 결정 로그 형식 확정 (`show-me-your-work` 축약판)
4. `benchmark-checklist` 7문항을 `docs/05-metrics.md`에 부록으로
5. 새 레포용 `AGENTS.md` 템플릿 (주석·산문 규칙 포함)
