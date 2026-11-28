# slopgate

> slop이 통과하지 못하는 검문소.
> 에이전트를 혼내는 대신, 검사로 막는다.

이름 그대로다. **slop**(검증되지 않은 산출물) + **gate**(검문소). 게이트를 통과하지 못하면 밖으로 나가지 않는다.

[Lauren Tan(poteto)의 강연 "All Code Is Slop (Except Mine)"](https://www.youtube.com/watch?v=O_zcc6Xl12g)
(2026-11, AI Engineer)의 논리를 내 Hermes 에이전트 운영에 옮기기 위한 준비 저장소다.
당장 적용하지 않는다. 방학에 4단계로 진행하고, 그 전에 기준선과 게이트 뼈대를 고정해 둔다.

## 왜 이 저장소가 필요한가

강연의 요지는 "에이전트가 slop을 만드는 걸 막는 방법은 프롬프트를 더 잘 쓰는 게 아니라,
에이전트가 실수할 수 없게 환경을 결정론적으로 조이는 것"이다.

문제는 내 Hermes에 **코드 레포가 아니라 산문이 주 입력**이라는 점이다.

| 입력 | 현재 크기 |
|---|---|
| 스킬 | 968개 활성 (+보관 129개), 매 세션 인덱스 주입 |
| 스킬 인덱스(이름+설명) | 118,731자 ≈ 30k 토큰/세션 |
| 상시 메모리 | MEMORY 19,439/20,000자 (97%), 57항목 |
| 크론 작업 | 15개(활성 8), 스크립트 40여 개 |

강연 논리를 그대로 옮기면 결론은 하나다.
**산문(스킬·AGENTS.md·메모리)에 적은 규칙은 강제되지 않는다. 실수가 반복되면 산문을 늘리지 말고 검사를 추가한다.**

이 저장소는 그 "검사"를 모으는 곳이다. 문서가 아니라 실행되는 스크립트가 본체다.

## 핵심 문장 3개

1. **교정할 때마다 산문 한 줄 대신 검사 하나를 추가한다.** 재현 가능하고, 리뷰에서 다시 생각할 필요가 없어진다.
2. **입력은 정원이다.** 에이전트는 기존 패턴을 복사한다. 안티패턴이 남아 있으면 다음 에이전트가 그것을 관례로 삼는다.
3. **토큰은 생성이 아니라 검증에 쓴다.** 생성 루프가 slop을 만들면 그 루프를 자동화할수록 slop만 늘어난다.

## 구성

```
gates/            실행되는 검사 (본체)
  skill_lint.py     스킬 frontmatter·참조 파일 실존·인덱스 예산·본문 크기
  memory_budget.py  상시 메모리 예산·장문 항목 이관 후보
  cron_lint.py      크론 프롬프트 길이·실효 프롬프트(첨부 스킬 본문 합계)·스크립트 실존·게이트 없는 무인 실행·도구/toolset 불일치
  runtime_check.py  자동화가 **실제로 돌았는가** — 연속 실패·스케줄러 정지·배달 실패·게이트 조회 실패 (실행 기록 기반)
  docs_lint.py      문서에 박힌 상승 카운터(체크 수·스킬 개수) 탐지 — 날짜 붙은 실측은 허용
  date_bomb.py      테스트 픽스처의 '가까운 미래' 날짜 리터럴 (지나면 CI가 조용히 깨진다)
  run_all.sh        전체 실행 + 요약 (+ --self-test, --repos)
tests/
  test_gates.py     게이트 자체 테스트 — 일부러 위반을 만들어 잡히는지 확인
scripts/
  split_skill.py    SKILL.md의 큰 절을 references/로 원문 그대로 옮긴다 (이관 검증 + 실패 시 복원)
  rewrite_descriptions.py  스킬 설명 배치 수정 (트리거 접두 추가)
docs/
  00-talk-notes.md     강연 주장 정리 (타임스탬프별) + 가져올 것/버릴 것
  01-model.md          코드 레포 → Hermes 대응 모델 (5계층)
  02-baseline.md       2026-11-25 실측 기준선
  03-gates.md          게이트 명세·오탐 위험·승격 조건
  04-roadmap.md        방학 4단계 계획 + 완료 기준
  05-metrics.md        성공 지표와 측정 방법
  06-open-questions.md 방학 전에 정할 것
  07-pstack.md         강연의 실제 산출물(pstack) 이식 목록 — 가져올 것/못 가져올 것
  08-audit-2026-11-26.md  강연 5원칙 준수 감사 — 원칙별 판정과 실측 근거
  09-audit-2026-11-28.md  오류 점검 — 변이 실험으로 찾은 결함 6건과 새 게이트 2개
templates/
  correction-to-gate.md  "또 같은 실수" → 게이트로 바꾸는 양식
  gate-spec.md           게이트 명세 양식
```

## 실행

```bash
bash gates/run_all.sh                    # 전체 (~/.hermes 위생)
bash gates/run_all.sh --self-test        # 게이트 자체 테스트 포함
bash gates/run_all.sh --repos ~/Documents/contest-mcp   # 날짜 폭탄 포함
python3 gates/skill_lint.py              # 개별
```

기본 대상은 `~/.hermes`다. 다른 경로를 검사하려면 `--skills-dir`, `--memories-dir`, `--jobs`를 준다.

## 지금 게이트 상태

`bash gates/run_all.sh`가 초록이다. 남은 경고는 세 종류이고 모두 **비용 경고**지 위반이 아니다:

- `SKL010` — description이 120자를 넘는다(인덱스 비용). 60자 제한은 `skill_manage(create)`의 API
  제약이지 파일 규칙이 아니다.
- `SKL011` — SKILL.md 본문이 40,000자를 넘는다(한 번 로드 비용). 분할 후보다.
- `SKL021` — 설명이 60자에서 잘려 "언제 쓰는지"가 인덱스에서 사라진다. 집계 1줄로만 보고한다.

여기에 숫자를 적지 않는 이유는 `gates/docs_lint.py`(DOC001)가 그것을 막기 때문이다 —
숫자는 문서가 아니라 **실행 출력**이 출처다. 단계별 수치와 그때의 판단은 `docs/02-baseline.md`에
날짜와 함께 남아 있다.

## 범위 밖

- 강연의 TLA+/Lean 형식 검증 — 내 산출물 규모에 비용이 맞지 않는다. `docs/01-model.md`에 이유를 적었다.
- 코드 주석 일괄 금지 — 기존 레포에 소급 적용하지 않는다. 새 레포에서만 시도한다.
- 자동 머지. 내 PR 규칙(리뷰 필수·승인 후 머지)과 정면으로 충돌한다. 자동화는 "게이트 통과한 초안 PR"까지만.

## 출처

- 강연: <https://www.youtube.com/watch?v=O_zcc6Xl12g>
- 한국어 해설(슬라이드 세부 보강): <https://youtu.be/ueA116hO_ho>
- pstack (강연에서 언급된 공개 플레이북): <https://github.com/cursor/plugins/tree/main/pstack>
