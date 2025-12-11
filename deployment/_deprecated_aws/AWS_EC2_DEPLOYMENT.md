# 🚀 AWS EC2 배포 가이드

실시간 트레이딩 봇을 AWS EC2에서 안정적으로 운영하기 위한 완전한 가이드

---

## 📋 목차

1. [EC2 인스턴스 생성](#ec2-인스턴스-생성)
2. [서버 초기 설정](#서버-초기-설정)
3. [프로젝트 배포](#프로젝트-배포)
4. [자동 실행 설정](#자동-실행-설정)
5. [모니터링 설정](#모니터링-설정)
6. [보안 설정](#보안-설정)
7. [문제 해결](#문제-해결)

---

## 🖥️ EC2 인스턴스 생성

### 권장 사양

**최소 사양:**
- 인스턴스 타입: **t3.micro** (프리티어)
- vCPU: 2
- 메모리: 1GB
- 스토리지: 20GB (gp3)
- OS: **Ubuntu 22.04 LTS**

**권장 사양 (안정성 향상):**
- 인스턴스 타입: **t3.small**
- vCPU: 2
- 메모리: 2GB
- 스토리지: 30GB (gp3)

### EC2 인스턴스 생성 단계

1. **AWS Console** → **EC2** → **인스턴스 시작**

2. **이름 및 태그**
   ```
   이름: bitcoin-trading-bot
   태그: Environment=Production, Project=TradingBot
   ```

3. **AMI 선택**
   - **Ubuntu Server 22.04 LTS (HVM), SSD Volume Type**
   - 64비트 (x86)

4. **인스턴스 타입**
   - t3.micro (프리티어) 또는 t3.small

5. **키 페어**
   - 새 키 페어 생성: `bitcoin-trading-bot-key`
   - 타입: RSA
   - 형식: .pem
   - **⚠️ 다운로드한 키 안전하게 보관**

6. **네트워크 설정**
   - VPC: 기본값
   - 서브넷: 자동 할당
   - 퍼블릭 IP: 자동 할당 활성화
   - 보안 그룹:
     ```
     이름: bitcoin-trading-bot-sg
     규칙:
     - SSH (22) - 내 IP만 허용
     ```

7. **스토리지 구성**
   - 크기: 20GB (최소) ~ 30GB (권장)
   - 볼륨 유형: gp3
   - 종료 시 삭제: 체크 해제 (데이터 보존)

8. **인스턴스 시작**

---

## 🔧 서버 초기 설정

### 1. SSH 접속

**로컬에서 키 파일 권한 설정:**
```bash
chmod 400 ~/Downloads/bitcoin-trading-bot-key.pem
```

**SSH 접속:**
```bash
ssh -i ~/Downloads/bitcoin-trading-bot-key.pem ubuntu@<EC2_PUBLIC_IP>
```

### 2. 시스템 업데이트

```bash
# 패키지 목록 업데이트
sudo apt update

# 시스템 업그레이드
sudo apt upgrade -y

# 필수 패키지 설치
sudo apt install -y \
    build-essential \
    git \
    wget \
    curl \
    vim \
    htop \
    tmux \
    python3.10 \
    python3.10-venv \
    python3-pip
```

### 3. TA-Lib 설치

```bash
# 의존성 설치
sudo apt install -y gcc g++ make

# TA-Lib 다운로드 및 설치
cd /tmp
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make
sudo make install

# 라이브러리 경로 업데이트
sudo ldconfig

# 확인
ls -l /usr/lib/libta_lib.*
```

### 4. Python 환경 설정

```bash
# Python 버전 확인
python3 --version  # Python 3.10.x 확인

# pip 업그레이드
python3 -m pip install --upgrade pip
```

---

## 📦 프로젝트 배포

### 방법 1: Git Clone (권장)

#### 1-1. GitHub에 푸시 (로컬에서)

**⚠️ 먼저 .env 파일이 .gitignore에 포함되어 있는지 확인!**

```bash
# 로컬에서 실행
cd /Users/harris/Development/private/bitcoin-trading-bot

# Git 초기화 (아직 안했다면)
git init

# .env 파일 제외 확인
cat .gitignore | grep .env

# 커밋
git add .
git commit -m "Add live trading system for production deployment"

# GitHub 리포지토리 생성 후
git remote add origin https://github.com/YOUR_USERNAME/bitcoin-trading-bot.git
git branch -M main
git push -u origin main
```

#### 1-2. EC2에서 Clone

```bash
# EC2에서 실행
cd ~
git clone https://github.com/YOUR_USERNAME/bitcoin-trading-bot.git
cd bitcoin-trading-bot
```

### 방법 2: SCP 전송

```bash
# 로컬에서 실행
cd /Users/harris/Development/private/bitcoin-trading-bot

# .env 제외하고 전송
rsync -avz --exclude '.env' \
    --exclude 'venv/' \
    --exclude '*.db' \
    --exclude '.git/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    -e "ssh -i ~/Downloads/bitcoin-trading-bot-key.pem" \
    . ubuntu@<EC2_PUBLIC_IP>:~/bitcoin-trading-bot/
```

---

## 🐍 Python 환경 구축

### 1. 가상환경 생성

```bash
cd ~/bitcoin-trading-bot

# 가상환경 생성
python3 -m venv venv

# 가상환경 활성화
source venv/bin/activate

# pip 업그레이드
pip install --upgrade pip
```

### 2. 라이브러리 설치

```bash
# requirements.txt 설치
pip install -r requirements.txt

# TA-Lib Python 래퍼 설치 (별도)
pip install TA-Lib

# 설치 확인
python -c "import talib; print('TA-Lib OK')"
python -c "import pyupbit; print('pyupbit OK')"
python -c "import telegram; print('telegram OK')"
```

---

## 🔑 환경 변수 설정

### .env 파일 생성

```bash
cd ~/bitcoin-trading-bot

# .env 파일 생성
nano .env
```

**내용 입력:**
```env
# 업비트 API 키
UPBIT_ACCESS_KEY=N3Tu6nHKL4l6dMzB4KOpYUQPycFd4Wfrv3zT61dq
UPBIT_SECRET_KEY=YzYJkqRBwM3EOfMxbk1DlvAojsx3Bj065G7ZgDcj

# 텔레그램 봇 정보
TELEGRAM_BOT_TOKEN=8304574463:AAHVDv0TCaQr-C1MW96xP8SseFf4I9RHelw
TELEGRAM_CHAT_ID=5940357912

# 거래 설정
INITIAL_CAPITAL=10000000
AUTO_TRADE=False
```

**저장:** `Ctrl + X` → `Y` → `Enter`

**권한 설정:**
```bash
chmod 600 .env  # 본인만 읽기/쓰기 가능
```

---

## 📊 데이터베이스 준비

### 로컬에서 DB 업로드

```bash
# 로컬에서 실행
scp -i ~/Downloads/bitcoin-trading-bot-key.pem \
    upbit_bitcoin.db \
    ubuntu@<EC2_PUBLIC_IP>:~/bitcoin-trading-bot/
```

### 또는 EC2에서 데이터 수집

```bash
# EC2에서 실행
cd ~/bitcoin-trading-bot
source venv/bin/activate

# 데이터 수집 (시간 소요: 약 10-20분)
python v1_db생성/upbit_bitcoin_collector.py
```

---

## 🔄 자동 실행 설정 (systemd)

### 1. systemd 서비스 파일 생성

```bash
sudo nano /etc/systemd/system/bitcoin-trading-bot.service
```

**내용:**
```ini
[Unit]
Description=Bitcoin Trading Bot (v35 Strategy)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/bitcoin-trading-bot/live_trading
Environment="PATH=/home/ubuntu/bitcoin-trading-bot/venv/bin"
ExecStart=/home/ubuntu/bitcoin-trading-bot/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=append:/home/ubuntu/bitcoin-trading-bot/logs/trading.log
StandardError=append:/home/ubuntu/bitcoin-trading-bot/logs/error.log

[Install]
WantedBy=multi-user.target
```

### 2. 로그 디렉토리 생성

```bash
mkdir -p ~/bitcoin-trading-bot/logs
```

### 3. 서비스 활성화 및 시작

```bash
# 서비스 리로드
sudo systemctl daemon-reload

# 서비스 활성화 (부팅 시 자동 시작)
sudo systemctl enable bitcoin-trading-bot

# 서비스 시작
sudo systemctl start bitcoin-trading-bot

# 상태 확인
sudo systemctl status bitcoin-trading-bot
```

### 4. 서비스 관리 명령어

```bash
# 중지
sudo systemctl stop bitcoin-trading-bot

# 재시작
sudo systemctl restart bitcoin-trading-bot

# 로그 확인
sudo journalctl -u bitcoin-trading-bot -f

# 로그 파일 확인
tail -f ~/bitcoin-trading-bot/logs/trading.log
tail -f ~/bitcoin-trading-bot/logs/error.log
```

---

## 📊 모니터링 설정

### 1. 실시간 로그 모니터링

```bash
# 트레이딩 로그
tail -f ~/bitcoin-trading-bot/logs/trading.log

# 에러 로그
tail -f ~/bitcoin-trading-bot/logs/error.log

# systemd 로그
sudo journalctl -u bitcoin-trading-bot -f
```

### 2. 시스템 리소스 모니터링

```bash
# CPU, 메모리 사용량
htop

# 디스크 사용량
df -h

# 네트워크 상태
netstat -tuln
```

### 3. 로그 로테이션 설정

```bash
sudo nano /etc/logrotate.d/bitcoin-trading-bot
```

**내용:**
```
/home/ubuntu/bitcoin-trading-bot/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    missingok
    copytruncate
}
```

---

## 🔒 보안 설정

### 1. 방화벽 설정 (UFW)

```bash
# UFW 활성화
sudo ufw enable

# SSH 허용 (⚠️ 먼저 설정!)
sudo ufw allow 22/tcp

# 상태 확인
sudo ufw status
```

### 2. SSH 보안 강화

```bash
# SSH 설정 파일 수정
sudo nano /etc/ssh/sshd_config
```

**변경사항:**
```
# 비밀번호 로그인 비활성화
PasswordAuthentication no

# 루트 로그인 비활성화
PermitRootLogin no

# 포트 변경 (선택)
Port 2222
```

**SSH 재시작:**
```bash
sudo systemctl restart sshd
```

### 3. 자동 업데이트 설정

```bash
# unattended-upgrades 설치
sudo apt install -y unattended-upgrades

# 활성화
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

### 4. Fail2Ban 설치 (SSH 공격 방지)

```bash
# 설치
sudo apt install -y fail2ban

# 시작
sudo systemctl start fail2ban
sudo systemctl enable fail2ban

# 상태 확인
sudo fail2ban-client status
```

---

## 🧪 테스트

### 1. 연결 테스트

```bash
cd ~/bitcoin-trading-bot/live_trading
source ../venv/bin/activate
python test_connection.py
```

**예상 결과:**
```
✅ 업비트 API: 성공
✅ 텔레그램 봇: 성공
🎉 모든 연결 테스트 성공!
```

### 2. 한 번 실행 테스트

```bash
python main.py --once
```

### 3. 서비스 상태 확인

```bash
sudo systemctl status bitcoin-trading-bot
```

---

## 🛠️ 문제 해결

### 서비스가 시작되지 않을 때

```bash
# 로그 확인
sudo journalctl -u bitcoin-trading-bot -n 50

# 권한 확인
ls -la ~/bitcoin-trading-bot/.env

# 경로 확인
which python
cat /etc/systemd/system/bitcoin-trading-bot.service
```

### TA-Lib import 오류

```bash
# 라이브러리 경로 확인
sudo ldconfig
ls -l /usr/lib/libta_lib.*

# 재설치
cd /tmp
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make
sudo make install
sudo ldconfig
```

### 메모리 부족

```bash
# 스왑 파일 생성 (2GB)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 영구 설정
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 확인
free -h
```

---

## 📋 체크리스트

### 배포 전

- [ ] .env 파일이 .gitignore에 포함되어 있는지 확인
- [ ] 로컬에서 연결 테스트 성공
- [ ] 로컬에서 한 번 실행 테스트 성공
- [ ] 업비트 API 키 권한 확인 (조회, 거래)
- [ ] 텔레그램 봇 작동 확인

### 배포 후

- [ ] EC2 SSH 접속 확인
- [ ] TA-Lib 설치 확인
- [ ] Python 라이브러리 설치 확인
- [ ] .env 파일 생성 및 권한 설정
- [ ] DB 파일 준비
- [ ] 연결 테스트 성공
- [ ] systemd 서비스 실행 확인
- [ ] 로그 확인
- [ ] 텔레그램 알림 수신 확인

### 운영 중

- [ ] 매일 텔레그램 확인
- [ ] 주간 로그 확인
- [ ] 월간 비용 확인 (AWS)
- [ ] 분기별 API 키 재발급 (권장)

---

## 💰 예상 비용

### AWS EC2 (서울 리전)

**t3.micro (프리티어):**
- 월 750시간 무료 (12개월)
- 초과 시: ~$10/월

**t3.small (권장):**
- 시간당: $0.0272
- 월간: ~$20/월

**스토리지 (gp3 30GB):**
- ~$3/월

**데이터 전송:**
- 아웃바운드 15GB 무료/월
- 초과 시: $0.126/GB

**총 예상 비용:**
- 프리티어: ~$3/월
- t3.small: ~$23/월

---

## 📞 지원

문제가 발생하면:

1. **로그 확인**
   ```bash
   sudo journalctl -u bitcoin-trading-bot -n 100
   ```

2. **텔레그램 에러 메시지 확인**

3. **서비스 재시작**
   ```bash
   sudo systemctl restart bitcoin-trading-bot
   ```

4. **디스크 공간 확인**
   ```bash
   df -h
   ```

---

**다음 단계:** [배포 자동화 스크립트](./deploy.sh) 참고
