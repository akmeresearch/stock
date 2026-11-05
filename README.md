# AKME Research

AI 기반 실적·시장 리서치 사이트. 사이트: https://akmeresearch.github.io/stock/

## 구조

```
.
├── index.html              # 시장 현황 (메인)
├── site/                   # 화면 (HTML/CSS/JS, GitHub Pages가 그대로 서빙)
├── data/                   # GitHub Actions가 수집해 커밋하는 JSON
│   ├── watchlist.json      # 관심종목 목록 (수동 관리)
│   ├── prices/             # 종목별 시세·수급
│   ├── financials/         # DART 분기 재무제표
│   ├── macro.json          # 금리·환율·심리지표
│   └── reports/            # Claude가 생성한 실적 분석 리포트 (markdown)
├── prompts/                # Claude 분석 지침 (earnings_analysis.md = 실적 분석 스킬)
├── scripts/                # 수집·분석 스크립트 (Python)
└── .github/workflows/      # 스케줄 자동화
```

## 동작 흐름

1. 매일 장 마감 후 GitHub Actions가 `scripts/collect_*.py`로 시세·수급·거시 데이터 수집 → `data/`에 JSON 저장
2. DART·EDGAR에 관심종목 실적 공시가 뜨면 `scripts/generate_report.py`가 Claude API로 분석 리포트 생성 → `data/reports/`
3. 커밋되면 GitHub Pages가 자동 재배포, 화면이 `data/`의 JSON을 읽어 표시

## 환경변수 (GitHub Secrets)

| 이름 | 용도 |
| --- | --- |
| `DART_API_KEY` | DART Open API |
| `ANTHROPIC_API_KEY` | Claude API |
| `KIS_APP_KEY`, `KIS_APP_SECRET` | 한국투자증권 Open API |
| `FRED_API_KEY` | FRED 거시지표 |

## 리포트 생성

Actions → **Generate earnings report** → Run workflow 에서 종목코드·분기·DART 접수번호를 넣으면
`scripts/generate_report.py`가 `prompts/earnings_analysis.md` 지침으로 Claude API를 호출해 `data/reports/`에 저장한다.
리포트 품질은 코드가 아니라 `prompts/earnings_analysis.md`를 고쳐서 조정한다.

## 로컬 실행

```bash
pip install -r requirements.txt
python scripts/collect_prices.py
```

---
정보 제공 목적이며 투자 권유가 아닙니다.
