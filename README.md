# Gmail 개별 발송 — 웹 버전

여러 명에게 단체 메일이 아니라 **개인 메일을 따로따로** 보내는 웹 프로그램입니다.
받는 사람들은 서로의 이메일 주소를 볼 수 없습니다. 맥·윈도우·모바일 어디서나 브라우저로 사용합니다.

---

## 1. 내 컴퓨터에서 먼저 테스트하기

```bash
cd gmail_web
pip3 install -r requirements.txt
python3 app.py
```

브라우저에서 **http://localhost:8000** 접속.

---

## 2. 인터넷에 올려서 링크로 공유하기 (무료)

다른 사람에게 링크를 주려면 인터넷 서버에 올려야 합니다.
가장 쉬운 무료 방법은 **Render**입니다.

### Render 배포 순서
1. 이 `gmail_web` 폴더를 GitHub 저장소에 올립니다.
   (또는 ZIP 업로드 방식 지원 호스트 사용)
2. https://render.com 가입 → **New → Web Service**
3. GitHub 저장소 연결
4. 설정값 입력:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --timeout 600 --workers 1`
5. **Create Web Service** 클릭 → 1~2분 후 `https://xxxx.onrender.com` 주소 발급
6. 이 주소를 다른 사람에게 공유하면 끝!

> 다른 무료 호스트(Railway, PythonAnywhere 등)도 동일한 방식으로 됩니다.
> `Procfile`과 `requirements.txt`가 이미 들어 있습니다.

---

## ⚠️ 중요 안내

- **앱 비밀번호는 서버에 저장되지 않습니다.** 발송 한 번에만 사용되고 버려집니다.
- 그래도 각 사용자는 **자기 Gmail의 앱 비밀번호**를 입력해야 합니다.
  (이 프로그램은 보내는 사람의 계정으로 발송하는 도구입니다)
- 반드시 **https 주소**(자물쇠 표시)에서 사용하세요. Render는 기본으로 https를 제공합니다.
- Gmail 하루 발송 한도: 일반 계정 약 500명/일, Workspace 약 2,000명/일.

---

## 파일 구성
```
gmail_web/
├── app.py              # 서버 (Flask)
├── templates/
│   └── index.html      # 화면
├── requirements.txt    # 필요한 라이브러리
├── Procfile            # 서버 실행 명령
└── README.md           # 이 문서
```
