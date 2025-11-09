# Project Overview
## 프로젝트 이름: 비트코인 트레이딩 봇 (Bitcoin Trading Bot)
## 목적: 시장 데이터를 기반으로 자동 매매 전략을 수행하고, 안정적인 수익을 추구하는 트레이딩 시스템 구축
## 주요 기능:
- 실시간 시세 수집 및 데이터 스트리밍
- 다중 전략 엔진 (v30~v35 등) 백테스트 및 실시간 실행
- 거래소 API 통합 (Binance, Upbit 등)
- 백테스트 및 성과 리포트 시각화
- 자동 포지션 관리 및 리스크 제어

# Tech Stack
## 언어: TypeScript, Python, Go
## 프레임워크: React 18, FastAPI, Gin
## 데이터베이스: PostgreSQL, Redis
## 인프라: Docker, Kubernetes, AWS (EKS, Lambda)

# Development Environment
## Node.js: v20.x LTS
## Python: 3.11+
## Package Manager: pnpm (Node.js), uv (Python)
## IDE: VS Code (권장 확장: Python, ESLint, Prettier, Docker)

# Build & Run Commands
## 개발 서버
```bash
npm run dev
```
## 빌드
```bash
npm run build
```
## 테스트
```bash
npm run test
```
## 린트
```bash
npm run lint
```
## 타입 체크
```bash
npm run typecheck
```

# Code Style & Conventions
## 언어별 스타일
- **TypeScript**: ES 모듈, 구조분해 할당 우선
- **Python**: Black 포매터, isort, mypy 타입 힌트
- **네이밍 규칙**: camelCase (JS/TS), snake_case (Python)

# 🚫 금지 사항 (중요!)
- `src/legacy` 디렉토리 파일 절대 수정 금지  
- `main` 브랜치에 직접 커밋 금지 (PR 필수)  
- 외부 API 키를 코드에 하드코딩 금지  
