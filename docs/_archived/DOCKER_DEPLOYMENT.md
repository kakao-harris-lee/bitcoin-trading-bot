# 🐳 Bitcoin Trading Bot - Docker Deployment Guide

**버전**: v35 Optimized (Optuna Trial 99)
**예상 2025 수익률**: +23.16%
**업데이트**: 2025-12-07

---

## 📋 목차

1. [개요](#개요)
2. [사전 준비](#사전-준비)
3. [빠른 시작](#빠른-시작)
4. [상세 가이드](#상세-가이드)
5. [운영 및 모니터링](#운영-및-모니터링)
6. [문제 해결](#문제-해결)

---

## 🎯 개요

Docker Compose를 사용하여 Bitcoin Trading Bot을 **어디서든** 쉽게 배포하고 운영할 수 있습니다.

### 주요 장점

✅ **이식성**: 로컬, 클라우드, VPS 어디서든 동일하게 실행
✅ **간편성**: 한 번의 명령으로 배포 완료
✅ **격리성**: 시스템 환경과 독립적으로 실행
✅ **재현성**: 동일한 환경을 항상 보장
✅ **확장성**: 쉬운 백업, 이전, 복제

### 시스템 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| **CPU** | 1 Core | 2 Core |
| **메모리** | 512MB | 1GB |
| **디스크** | 2GB | 5GB |
| **Docker** | 20.10+ | 최신 버전 |
| **Docker Compose** | 1.29+ | 2.x |

---

## 🔧 사전 준비

### 1. Docker 설치

#### macOS
```bash
# Homebrew 사용
brew install --cask docker

# 또는 공식 사이트에서 다운로드
# https://docs.docker.com/desktop/mac/install/
```

#### Ubuntu/Debian
```bash
# Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 현재 사용자를 docker 그룹에 추가
sudo usermod -aG docker $USER

# 로그아웃 후 재로그인
```

#### Windows
```
Docker Desktop for Windows 다운로드 및 설치
https://docs.docker.com/desktop/windows/install/
```

### 2. Docker Compose 설치

#### Docker Desktop (macOS/Windows)
Docker Desktop에 포함되어 있음 (별도 설치 불필요)

#### Linux
```bash
# Docker Compose V2 (권장)
sudo apt-get update
sudo apt-get install docker-compose-plugin

# 확인
docker compose version
```

### 3. 설치 확인

```bash
# Docker 버전 확인
docker --version
# Docker version 24.0.0 이상

# Docker Compose 버전 확인
docker compose version
# Docker Compose version v2.20.0 이상
```

---

## 🚀 빠른 시작

### 1단계: 프로젝트 준비

```bash
cd /path/to/bitcoin-trading-bot

# .env 파일 생성
cp .env.example .env
nano .env
```

**.env 파일 내용**:
```bash
# 업비트 API (필수)
UPBIT_ACCESS_KEY=your_access_key
UPBIT_SECRET_KEY=your_secret_key

# 텔레그램 (필수)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 바이낸스 (선택, VPN 필요할 수 있음)
BINANCE_API_KEY=your_binance_key
BINANCE_API_SECRET=your_binance_secret

# 거래 설정
AUTO_TRADE=False
```

### 2단계: 배포 실행

```bash
# 배포 스크립트 실행
./deployment/deploy_docker.sh start
```

### 3단계: 확인

```bash
# 컨테이너 상태 확인
./deployment/deploy_docker.sh status

# 실시간 로그 확인
./deployment/deploy_docker.sh logs
```

**완료!** 🎉

---

## 📚 상세 가이드

### 수동 배포 (deploy_docker.sh 미사용)

#### 1. 이미지 빌드
```bash
docker compose build
```

#### 2. 컨테이너 시작
```bash
docker compose up -d
```

#### 3. 로그 확인
```bash
docker compose logs -f trading-bot
```

### 환경 변수 설명

| 변수 | 필수 | 설명 |
|------|------|------|
| `UPBIT_ACCESS_KEY` | ✅ | 업비트 API Access Key |
| `UPBIT_SECRET_KEY` | ✅ | 업비트 API Secret Key |
| `TELEGRAM_BOT_TOKEN` | ✅ | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | ✅ | 텔레그램 Chat ID |
| `BINANCE_API_KEY` | ❌ | 바이낸스 API Key (헤지용) |
| `BINANCE_API_SECRET` | ❌ | 바이낸스 Secret Key |
| `AUTO_TRADE` | ✅ | 자동 거래 활성화 (True/False) |

### 볼륨 매핑

```yaml
volumes:
  - ./logs:/app/logs                    # 로그 파일
  - ./upbit_bitcoin.db:/app/upbit_bitcoin.db:ro  # DB (읽기 전용)
  - ./strategies/v35_optimized/config_optimized.json:/app/strategies/v35_optimized/config_optimized.json:ro
```

**설명**:
- 로그는 호스트의 `./logs` 디렉토리에 저장
- DB 파일은 읽기 전용으로 마운트
- 설정 파일 변경 시 컨테이너 재시작 필요

---

## 🔄 운영 및 모니터링

### 배포 스크립트 사용

```bash
# 컨테이너 시작
./deployment/deploy_docker.sh start

# 컨테이너 중지
./deployment/deploy_docker.sh stop

# 컨테이너 재시작
./deployment/deploy_docker.sh restart

# 실시간 로그
./deployment/deploy_docker.sh logs

# 상태 확인
./deployment/deploy_docker.sh status

# 이미지 재빌드
./deployment/deploy_docker.sh build

# 전체 삭제
./deployment/deploy_docker.sh clean
```

### Docker Compose 직접 사용

```bash
# 컨테이너 시작
docker compose up -d

# 컨테이너 중지
docker compose down

# 로그 확인 (최근 100줄)
docker compose logs --tail=100 trading-bot

# 실시간 로그
docker compose logs -f trading-bot

# 컨테이너 재시작
docker compose restart trading-bot

# 컨테이너 상태
docker compose ps

# 리소스 사용량
docker stats bitcoin-trading-bot-v35-optimized
```

### 컨테이너 내부 접속

```bash
# Bash 접속
docker compose exec trading-bot bash

# Python 쉘
docker compose exec trading-bot python

# 특정 명령 실행
docker compose exec trading-bot python -c "import pyupbit; print(pyupbit.get_current_price('KRW-BTC'))"
```

### 로그 관리

```bash
# 로그 파일 위치
ls -lh logs/

# 최근 로그 확인
tail -f logs/trading.log

# 에러 로그
tail -f logs/error.log

# 로그 정리 (30일 이상)
find logs/ -name "*.log" -mtime +30 -delete
```

---

## 🌐 클라우드/VPS 배포

### 일반 VPS (DigitalOcean, Linode, Vultr 등)

```bash
# 1. SSH 접속
ssh user@your-server-ip

# 2. Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# 3. 프로젝트 복사
git clone https://github.com/your-repo/bitcoin-trading-bot.git
cd bitcoin-trading-bot

# 4. .env 파일 생성
nano .env

# 5. 배포
./deployment/deploy_docker.sh start
```

### AWS EC2

```bash
# Amazon Linux 2023
sudo yum install -y docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user

# 프로젝트 배포 (위와 동일)
```

### GCP Compute Engine

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER

# 프로젝트 배포 (위와 동일)
```

### 바이낸스 접속 가능 지역

**중요**: 바이낸스 선물 거래는 특정 지역에서 제한됩니다.

✅ **접속 가능 지역** (VPS 추천):
- 🇰🇷 한국 (Seoul)
- 🇯🇵 일본 (Tokyo)
- 🇸🇬 싱가포르 (Singapore)
- 🇩🇪 독일 (Frankfurt)
- 🇬🇧 영국 (London)

❌ **제한 지역**:
- 🇦🇺 호주 (Sydney) - 확인됨
- 🇺🇸 미국 일부 주

**권장 VPS 제공업체** (바이낸스 허용):
- Contabo (독일)
- Vultr (서울, 도쿄)
- DigitalOcean (싱가포르)

---

## 🔒 보안 설정

### 1. .env 파일 보호

```bash
# 권한 설정 (본인만 읽기/쓰기)
chmod 600 .env

# Git에 추가되지 않도록 확인
cat .gitignore | grep .env
```

### 2. 컨테이너 보안

`docker-compose.yml`에 이미 적용됨:
- 비root 사용자로 실행 (`USER trader`)
- CPU/메모리 제한 설정
- 읽기 전용 볼륨 마운트

### 3. 네트워크 보안

```bash
# 방화벽 설정 (선택)
sudo ufw allow 22/tcp  # SSH만 허용
sudo ufw enable
```

---

## ⚙️ 설정 변경

### Auto Trade 활성화

```bash
# .env 파일 수정
nano .env

# AUTO_TRADE=False → AUTO_TRADE=True 변경

# 컨테이너 재시작
./deployment/deploy_docker.sh restart
```

### 전략 설정 변경

```bash
# config_optimized.json 수정
nano strategies/v35_optimized/config_optimized.json

# 컨테이너 재시작 (설정 적용)
./deployment/deploy_docker.sh restart
```

### 리소스 제한 조정

`docker-compose.yml` 수정:
```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'      # CPU 제한 증가
      memory: 2G       # 메모리 제한 증가
```

---

## 🛠️ 문제 해결

### 컨테이너가 시작되지 않음

```bash
# 로그 확인
docker compose logs trading-bot

# 컨테이너 상태
docker compose ps

# 이미지 재빌드
./deployment/deploy_docker.sh build
```

### .env 파일 오류

```bash
# .env 파일 형식 확인
cat .env

# 줄바꿈 문자 확인 (Windows vs Unix)
file .env

# 권한 확인
ls -la .env
```

### 메모리 부족

```bash
# 현재 사용량 확인
docker stats bitcoin-trading-bot-v35-optimized

# docker-compose.yml에서 메모리 제한 증가
# MemoryLimit: 1G → 2G
```

### 디스크 공간 부족

```bash
# Docker 디스크 사용량 확인
docker system df

# 사용하지 않는 이미지/컨테이너 삭제
docker system prune -a

# 로그 정리
find logs/ -name "*.log" -mtime +7 -delete
```

### 바이낸스 연결 실패

**에러**: "Service unavailable from a restricted location"

**해결**:
1. VPS 위치 확인 (바이낸스 허용 지역인지)
2. VPN 사용 (권장하지 않음, 약관 위반 가능)
3. 바이낸스 없이 운영 (현금 전환 모드)

---

## 📊 백업 및 복원

### 백업

```bash
# 전체 백업
tar -czf backup-$(date +%Y%m%d).tar.gz \
  .env \
  upbit_bitcoin.db \
  logs/ \
  strategies/v35_optimized/config_optimized.json

# 백업 확인
ls -lh backup-*.tar.gz
```

### 복원

```bash
# 백업 압축 해제
tar -xzf backup-20251207.tar.gz

# 컨테이너 재시작
./deployment/deploy_docker.sh restart
```

### 자동 백업 (cron)

```bash
# crontab 편집
crontab -e

# 매일 새벽 3시 백업
0 3 * * * cd /path/to/bitcoin-trading-bot && tar -czf backup-$(date +\%Y\%m\%d).tar.gz .env upbit_bitcoin.db logs/
```

---

## 📈 성능 최적화

### 로그 로테이션

`docker-compose.yml`에 이미 적용됨:
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

### 리소스 모니터링

```bash
# 실시간 모니터링
docker stats bitcoin-trading-bot-v35-optimized

# 리소스 사용 기록
docker stats --no-stream bitcoin-trading-bot-v35-optimized >> stats.log
```

---

## 🆚 Docker vs systemd 비교

| 항목 | Docker | systemd (EC2) |
|------|--------|---------------|
| **이식성** | ✅ 우수 | ❌ 낮음 |
| **설치 난이도** | ✅ 쉬움 | ⚠️ 보통 |
| **리소스 격리** | ✅ 완벽 | ❌ 없음 |
| **백업/복원** | ✅ 간편 | ⚠️ 복잡 |
| **성능** | ⚠️ 약간 낮음 | ✅ 최고 |
| **디버깅** | ⚠️ 보통 | ✅ 쉬움 |
| **권장 용도** | 로컬, VPS | 전용 서버 |

---

## 📞 지원

### 로그 수집

문제 발생 시 다음 정보를 수집하세요:

```bash
# 1. 컨테이너 상태
docker compose ps > debug_info.txt

# 2. 최근 로그
docker compose logs --tail=100 trading-bot >> debug_info.txt

# 3. 리소스 사용량
docker stats --no-stream bitcoin-trading-bot-v35-optimized >> debug_info.txt

# 4. 시스템 정보
docker version >> debug_info.txt
docker compose version >> debug_info.txt
```

---

## 🎉 완료!

Docker Compose 배포가 완료되었습니다.

### 다음 단계

1. **모니터링**: 첫 24시간 동안 로그 확인
2. **테스트**: Paper Trading 모드로 1주일 테스트
3. **실거래**: AUTO_TRADE=True로 전환
4. **백업**: 정기 백업 설정

### 유용한 링크

- [Docker 공식 문서](https://docs.docker.com/)
- [Docker Compose 문서](https://docs.docker.com/compose/)
- [프로젝트 README](README.md)
- [배포 체크리스트](DEPLOYMENT_CHECKLIST.md)

---

**작성일**: 2025-12-07
**버전**: v1.0
**배포 상태**: ✅ Ready for Production
