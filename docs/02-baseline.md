# 기준선 — 2026-11-25 실측

대상: `~/.hermes` (macOS, macOS 27.2.1)
측정: 이 저장소의 게이트 3개 + 몇 개의 `find`/`wc`.

## 요약

| 항목 | 값 | 게이트 | 판정 |
|---|---|---|---|
| 활성 스킬 | 968개 (보관 `.archive/` 129개 별도) | — | — |
| 스킬 지원 문서 | 1,986개 마크다운 | — | — |
| 스킬 디렉터리 용량 | 172MB | — | — |
| 스킬 인덱스(이름+설명) | **118,731자** ≈ 30k 토큰/세션 | `SKL020` | 경고 |
| frontmatter 누락 | 0건 | `SKL001/002` | 통과 |
| 참조 파일 깨짐 | **12건** | `SKL003` | **실패** |
| description 120자 초과 | 62건 | `SKL010` | 경고 |
| SKILL.md 40,000자 초과 | 8건 | `SKL011` | 경고 |
| MEMORY.md | **15,648 / 20,000자 (78%)**, 56항목 (97%→78%, 2026-11-26) | `MEM003` | 통과 |
| MEMORY 장문 항목(>400자) | 5건 (21→5, 2026-11-26) | `MEM004` | 경고 |
| USER.md | 4,803 / 8,000자 (60%), 29항목 | — | 통과 |
| 크론 작업 | 15개 (활성 8) | — | — |
| 크론 프롬프트 > 9,500자 | ~~1건 (9,531자)~~ → **0건** (9,531 → 2,918자, 2026-11-26) | `CRN001` | 통과 |
| 크론 스크립트 경로 누락 | 0건 | `CRN002` | 통과 |
| 후보 게이트 없는 활성 에이전트 크론 | 1건 | `CRN010` | 경고 |

## 2026-11-26 갱신

1단계 정리 후 실측. 게이트 전체가 **통과**(오류 0).

| 항목 | 2026-11-25 | 2026-11-26 |
|---|---|---|
| SKL003 깨진 참조 | 12건 (실패) | **0건** |
| CRN001 크론 프롬프트 초과 | 1건 (9,531자) | **0건** (2,918자) |
| 스킬 수 | 968 | 970 (+2: slopgate·hermes-sweeper-runbook) |
| 스킬 인덱스(60자 클립 실비용) | 97,590자 (≈24k 토큰) | 99,617자 (+2,027: 트리거 접두 119건) |
| 원본 설명 총량 | 245,679자 | 251,626자 |
| MEMORY.md | 19,439 / 20,000자 (97%) | **15,648 / 20,000자 (78%)** |
| MEMORY 장문 항목(>400자) | 21건 | **5건** |
| 정적 게이트 | 오류 1 (CRN001) | **오류 0** |
| 런타임 게이트(RT) | (없었음, 그래서 못 봤다) | 오류 1 적발 → 원인 수정 → **오류 0** |

#### RT001이 잡은 실제 사례 (2026-11-26)

`SI-Weekly-Memory-Cron-Check`가 **928초 모델 타임아웃으로 2회 연속 실패**한 상태로 98시간 방치돼 있었다.
정적 게이트 4종은 전부 "정상"이라고 답했다 — 설정과 파일은 완벽했기 때문이다.

원인: 그 크론이 `hermes cron list`·메모리 전문·세션 검색을 **한 세션에서 직접** 읽으라고 지시받아,
모델 응답을 15분 넘게 기다리다 중단됐다. 판단(정리·교훈)과 수집(숫자)을 한 덩어리로 시킨 설계 문제.

수정: 수집을 `~/.hermes/scripts/weekly-digest.py`로 분리해 크론의 `script`로 주입하고, 에이전트는
주입된 값만 읽고 판단만 하도록 프롬프트를 다시 썼다. 재실행 결과 **응답 734자, status `ok`,
failure_streak 2 → 0**.

그 실행에서 프롬프트가 **61,750자**인 것을 발견했다. 원인은 첨부 스킬 `pre-task-routine` +
`hermes-agent` 본문이 함께 주입된 것 — 프롬프트 자체는 2,433자였다. 그 두 스킬은 이 크론의 판단에
기여하지 않고(수집은 스크립트가 끝냈고, 절차는 프롬프트에 다 있다) 회차마다 15k 토큰을 태우고 있었다.
첨부를 비우고 재실행: **프롬프트 61,750 → 2,433자(96% 감소), 응답은 400자로 더 간결해졌고 판정은 동일**
(`ok`, 오류 0). 교훈: 첨부 스킬은 "본문이 들어간다"는 비용을 항상 계산해야 한다.

깨진 참조 12건의 처리 방식은 `docs/03-gates.md`의 오탐 위험 항목과 같이 봐야 한다.
공통 문서는 **각 스킬 디렉터리 안에 복제 생성**(11개), 이미 있는 파일을 가리키던 문장은 **경로만 정정**(5건).
`hermes-agent`의 2건은 내용이 현재 코드와 어긋나 문서로 옮기면 틀린 지식이 굳으므로, **실재하는 소스 파일과 테스트를 가리키게** 바꿨다.

### 인덱스 측정 정정 (2026-11-26)

처음엔 인덱스 비용을 118,877자로 적었다. 두 가지가 틀렸다.
1. **frontmatter 파서가 첫 줄만 읽었다** — 766개 스킬이 `description: >-` 형태의 여러 줄 설명이라 원본 총량을 3분의 1로 축소 계산했다(실제 295,194자).
2. **60자 클립을 무시했다** — Hermes는 시스템 프롬프트 인덱스에서 설명을 60자로 자른다(`SKILL_PROMPT_DESC_LIMIT`). 잘린 뒤 길이가 실제 세션 비용이다.

정정된 값: 스킬 인덱스 **99,617자 ≈ 25k 토큰/세션**. 게이트에 `SKL021`(60자 안에 트리거가 없는 스킬 집계)을 추가했고, 현재 **855 → 745건**이다.

### yaml 없는 환경에서 파서가 다시 틀렸다 (2026-11-26, CI 적발)

위 정정은 `yaml.safe_load`를 쓰는 경로에서만 참이었다. 게이트는 PyYAML이 없으면 자체 줄 단위
파서로 떨어지는데, 그 파서가 `description: >-`의 마커를 **값으로** 읽어 설명 길이를 2자로 계산했다.
로컬에는 yaml이 설치돼 있어 이 경로가 한 번도 실행되지 않았고, CI 러너에서만 자체 테스트가 깨졌다.

- 증상: `raw_desc_chars`가 89자가 아니라 2자. 인덱스 비용을 99% 과소평가한다.
- 범위: 블록 스칼라(`>-`·`|`)뿐 아니라 **이어지는 들여쓴 평문 줄**과 **여러 줄 인용 문자열**도 같은
  방식으로 잘렸다. 실제 트리 970개 중 663개(짧아진 쪽 659개)가 영향을 받았고, 누락 합계 112,796자였다.
- 수정: fallback 파서가 ① 블록 스칼라 ② 들여쓴 뒷줄 접기 ③ 여러 줄 인용을 모두 이어 붙이게 했다.
  YAML 단일 인용의 이스케이프(`''`)를 닫는 따옴표로 오판하지 않도록 별도 처리했다.
- 남은 편차(같은 PR에서 추가 수정): 첫 수정 뒤에도 인용 스칼라의 **이스케이프된 큰따옴표**(`\"`),
  **블록 마커 변형**(`>2-`, `>-  # note`), **인용 안의 `#` 줄**에서 fallback이 값을 잘랐다.
  실제 트리 970개에는 해당 사례가 0건이지만 같은 부류라 함께 고쳤다 — 인용 해석을 `unquote()`
  한 곳으로 모으고, 단일/이중 인용 이스케이프와 마커 문법을 그 함수가 처리한다.
- 결과: 두 경로의 `index_chars`가 **99,617자로 완전히 일치**하고, `raw_desc_chars`도 이제
  **251,626 vs 251,626으로 완전히 같다**(수정 전 251,426, 200자 차이).
  엣지 케이스 19종(블록 스칼라·접기·인용 이스케이프·마커 변형·빈 블록·인용 내 `#`)을 yaml과 대조해 전부 일치.
- 판정 뒤집힘도 하나 있었다: `description: ~`(YAML null)을 fallback이 문자열 `~`로 읽어,
  yaml 경로에서는 `SKL002`(설명 없음, 오류 → exit 1)인 파일이 무 yaml 환경에서는 통과했다.
  null 토큰(`~`·`null`·`NULL`)을 빈 값으로 처리해 두 경로의 판정을 맞췄다.
- 남은 차이는 **타입 강제**뿐이다: `yes`/`no` 같은 YAML 1.1 불리언은 yaml 경로가 `True`/`False`로,
  fallback은 문자열 그대로 읽어 2~3자 어긋난다(판정에는 영향 없음 — 트리에 그런 설명은 0건).
  YAML 타입 시스템을 재구현하는 대신, 결과 `summary.parser`에 **어느 경로가 수치를 냈는지**를 남겨
  두 경로가 갈라졌을 때 출력만으로 알아챌 수 있게 했다(사람용 요약에도 `· 파서 yaml` 표기).

교훈: 게이트에 fallback 경로가 있으면 **그 경로도 테스트가 직접 실행해야 한다**. 테스트를 돌린
환경에 우연히 라이브러리가 있으면 대체 경로는 영원히 검증되지 않는다. 자체 테스트에 yaml import를
차단한 실행기(`run_gate_no_yaml`)를 넣어 두 경로의 값이 같은지 대조한다.
두 번째 교훈: **"같은 값을 낸다"를 값 하나로 판정하지 말 것**. 실제 트리에서 `index_chars`가 일치해도
`raw_desc_chars`는 200자 어긋나 있었고, 그 200자가 곧 남은 파서 결함의 위치를 가리켰다.

### 인덱스 비용의 81%는 자동 설치 팩 하나 (2026-11-26 발견)

스킬 988개를 작성자별로 집계하면 비용 구조가 바로 보인다.

| 작성자 | 스킬 수 | 인덱스 점유 |
|---|---|---|
| `mahipal` (Anthropic-Cybersecurity-Skills 팩, Apache-2.0) | 770 | 82,058자 (**81%**, ≈20.5k 토큰) |
| 그 외(내 작업용 + Hermes 번들 + addyosmani) | 218 | 19,059자 (≈4.8k 토큰) |

이 팩은 `~/.hermes/skills/.hub/taps.json`의 `mukul975/Anthropic-Cybersecurity-Skills` 탭에서 설치됐고,
**전체 세션 이력에서 12번(9개 스킬)만 호출됐다.** 나머지 761개는 한 번도 쓰이지 않았다.
반면 내 작업용 스킬 218개는 104개가 실제로 호출됐다.

즉 "설명을 짧게 쓰자"보다 **"한 번도 안 쓴 761개를 인덱스에서 빼자"** 가 40배 큰 절감이다
(약 20.3k 토큰/세션 vs 설명 1~2k). 다만 `.archive/`로 옮기면 `skill_view`로도 못 찾는다
(`EXCLUDED_SKILL_DIRS`가 인덱스와 조회 양쪽에서 제외) — 필요할 때 되돌리는 비용이 있다.
결정은 `docs/06-open-questions.md` Q8로 올렸다.

### 트리거 접두 작업 (2026-11-26, 1차분 119건)

문제는 비용이 아니라 **선택 가능성**이다. 인덱스에 `Parse and analyze Cobalt Strike Malleable C2 profiles...` 처럼
"무엇을 하는지"만 보여서는 에이전트가 자기 상황에서 그 스킬을 꺼낼 판단을 못 한다.

기존 설명을 요약·압축하는 대신 **앞에 트리거 문장만 붙였다**(`scripts/rewrite_descriptions.py --mode prefix`).
정보 손실 0, YAML 키 변경 0, 본문 변경 0을 스크립트가 검증하고, 119건 적용 후 재검증도 통과했다.
백업: `~/.hermes/state/slopgate/desc-backup-20261126-121214/` (119파일).

크론 프롬프트는 절차 본문을 스킬 `hermes-sweeper-runbook`으로 옮기고 프롬프트를 2,918자로 줄였다.
축약 과정에서 규칙이 사라지지 않았는지는 원본 39개 규칙을 하나씩 대조해 확인했다(사라진 규칙 0건).

## 깨진 참조 12건 (해결 전 기록)

| 스킬 | 없는 파일 |
|---|---|
| `autonomous-ai-agents/hermes-agent` | `references/execute-code-sandbox-env-windows.md`, `references/prompt-builder-environment-hints.md` |
| `code-review-and-quality` | `references/performance-checklist.md`, `references/security-checklist.md` |
| `performance-optimization` | `references/performance-checklist.md` |
| `security-and-hardening` | `references/security-checklist.md` |
| `shipping-and-launch` | `references/accessibility-checklist.md`, `references/definition-of-done.md`, `references/performance-checklist.md`, `references/security-checklist.md` |
| `planning-and-task-breakdown`, `incremental-implementation`, `using-agent-skills` | `references/definition-of-done.md` |
| `mem0-verification-and-diagnostics` | `scripts/probe-provider-key.py` |
| `verifying-agent-written-code` | `references/delegated-agent-runs.md` |
| `research/mogef-ai-benchmark-challenge` | `scripts/{analyze,auto_resume,build_submission,run_benchmark}.py` |
| `research/korean-contest-proposal` | `scripts/fill_hwpx_cells.py` |

패턴이 보인다. `definition-of-done.md`, `security-checklist.md`, `performance-checklist.md`는 **여러 스킬이 같은 파일을 가정**하는데 실제로는 없다. 한 번 만들면 9건이 동시에 해결되는 구조다.

## 해석

1. **가장 큰 비용은 스킬 인덱스다.** 세션마다 30k 토큰이 설명 목록에 나간다. 강연의 "산문은 마지막 층에 소량"과 정면으로 어긋난 상태다. 다만 968개를 무작정 줄이면 스킬 선택 정확도가 떨어질 수 있다. 예산을 정하고 그 안에서 정리하는 순서가 맞다 (`docs/06-open-questions.md` Q2).
2. **깨진 참조는 조용히 실패한다.** 에이전트는 스킬을 믿고 `read_file`을 호출하고, 없으면 즉석에서 우회한다. 이때 우회 결과가 정상처럼 보이는 게 더 나쁘다. 12건은 30분이면 정리된다.
3. **메모리 97%는 이미 위험 구간이다.** 새 사실을 저장할 때 가장 오래된 항목이 밀려나는데, 무엇이 사라졌는지는 아무도 기록하지 않는다.
4. **크론 1건은 지금 깨져 있다.** 9,531자 프롬프트는 `cronjob_manage(update)`로 수정할 수 없다(페이로드 잘림). 이 저장소를 만든 계기 중 하나이기도 하다.

## 재현

```bash
bash gates/run_all.sh
python3 gates/skill_lint.py --json | jq '.summary'
python3 gates/memory_budget.py
python3 gates/cron_lint.py

# 인덱스 문자수는 SKL020이 출력한다. 토큰 근사는 4자/토큰으로 나눈 값.
```

## 남은 측정 (아직 안 함)

- 토큰 사용 분포: 생성 vs 검증 vs 리뷰 (`docs/05-metrics.md`)
- PR revert율 — 이 저장소 게이트와 무관하게 별도 측정 필요
- 스킬 인덱스의 실제 토크나이저 비용 (4자/토큰 근사는 ±15% 오차)
