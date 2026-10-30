# 한국어 장단음 분석기

표준발음법에 따라 길게 발음해야 하는 음절(장음)을 표시하고 판단 근거를 보여 주는 도구입니다. 

공개 서버: https://jangdan-436361020679.asia-northeast3.run.app

## 배경

표준발음법은 모음의 장단을 구별해 발음하는 것을 원칙(제3장 제6항, 제7항)으로 하지만, 현대 서울·경기 화자는 장단을 거의 구별하지 못합니다. 장단음은 동형이의어, 활용형에 따라 달라져 규칙 기반 판단은 한계가 있습니다.

- 동형어: 방화(防火)[방화] / 방화(放火)[방ː화]
- 활용형: 알다[알ː다] / 알아[아라]

따라서 원고를 규범대로 읽으려면 단어마다 사전을 찾아야 합니다. 이 도구는 아나운서나 성우 지망생처럼 원고를 규범 발음으로 읽어야 하는 사람이 사전을 찾는 수고를 덜도록 돕습니다.

## 처리 흐름

(추가예정)

## 구성

(추가예정)

## 실행

1. 의존성을 설치합니다(Python 3.12): `pip install -r requirements.txt`
2. 사전 DB를 만듭니다: `python -m prep.build`. 원시 데이터 폴더는 `JANGDAN_RAW_DIR`로 바꿀 수 있습니다.
3. `.env`에 설정을 넣습니다.
   - `GEMINI_API_KEY`: 동형어 판별에 쓰는 LLM 키입니다. 없으면 판별이 필요한 단어를 그대로 둡니다.
   - `JANGDAN_DB_SOURCE=turso`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`: 로컬 DB 대신 Turso를 읽습니다.
4. 화면을 빌드합니다(Node.js 22.12 이상): `web` 폴더에서 `npm install`, `npm run build`
5. 서버를 켭니다: `uvicorn api.main:create_app --factory`. `http://localhost:8000`에서 화면이 열립니다.
6. API만 쓸 때는 `POST /api/analyze`에 `{"text": "원고"}`를 보내면 장음 표시 결과와 근거를 돌려줍니다. `http://localhost:8000/docs`에서 시험할 수 있습니다.

## 브라우저 확장

Chrome에서 글을 선택하고 확장 아이콘을 누르면, 선택한 글의 장음을 팝업에 표시합니다. 선택한 글이 없으면 팝업에 직접 붙여 넣을 수 있습니다.

1. `extension` 폴더에서 `npm install`, `npm run build`를 실행합니다. 분석 서버 주소의 기본값은 공개 서버이며, 로컬 서버를 쓰려면 빌드할 때 환경 변수 `WXT_API_BASE`에 `http://localhost:8000`을 넣습니다.
2. Chrome의 `chrome://extensions`에서 개발자 모드를 켜고, 「압축해제된 확장 프로그램을 로드합니다」로 `extension/.output/chrome-mv3` 폴더를 불러옵니다.

## 배포

Google Cloud Run(서울 리전)에 배포했습니다. 사전 DB는 Turso에서 읽고, 키는 Secret Manager에 둡니다.

1. 이미지를 빌드합니다: `gcloud builds submit --machine-type=e2-standard-2 --tag <이미지 주소>`
2. 서비스를 배포합니다: `gcloud run deploy jangdan --image <이미지 주소> --memory 1Gi --max-instances 1 --allow-unauthenticated`
   - 환경 변수: `JANGDAN_DB_SOURCE=turso`, `TURSO_DATABASE_URL`, `JANGDAN_RATE_PER_MIN`(주소당 분당 요청 수), `JANGDAN_LLM_PER_DAY`(하루 LLM 호출 수. 넘으면 문맥 판별 없이 답합니다). 두 한도는 값이 없거나 0이면 두지 않습니다.
   - 비밀값(`--set-secrets`): `GEMINI_API_KEY`, `TURSO_AUTH_TOKEN`

## 데이터

- 국립국어원의 한국어기초사전과 표준국어대사전의 전체 내려받기 파일을 사용합니다.
- `prep/stdict_conj_pron.csv`는 표준국어대사전 웹 페이지에서 모은 활용 발음입니다(출처: 국립국어원 표준국어대사전, CC BY-SA 2.0 KR).