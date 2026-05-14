# Running movensys-monopoly
## 1. 로컬 개발 (uvicorn)

### 의존성 설치 (최초 1회)

Ubuntu 24.04 (Python 3.12, PEP 668):

```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly
pip3 install --break-system-packages -r requirements.txt
```

또는 venv 사용:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 실행

```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly
python3 -m uvicorn main:app --host 0.0.0.0 --port 7999
```

### 종료

```bash
pkill -f 'uvicorn main:app'
```

확인:

```bash
pgrep -fa 'uvicorn main:app' || echo "no uvicorn running"
```

---

## 2. Docker Compose

### 실행

```bash
cd docker
docker compose down
docker compose up -d --build
docker compose up
```

### 로그

```bash
docker compose logs -f robopoly
```