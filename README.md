# 반계리 은행나무 관측소 — 매시 자동 관측판

GitHub Actions가 매시 영상에서 사진을 한 장씩 받아 `data/` 에 쌓고, `index.html` 이 그 기록을 읽어 보여 줍니다.
컴퓨터를 켜 둘 필요가 없습니다.

```
index.html                    앱 (GitHub Pages로 공개)
capture.py                    매시 실행: 사진 받기 → 단풍·잎 계산 → data/ 에 기록
.github/workflows/capture.yml 매시 실행 일정
data/data.json                기록 (처음엔 비어 있고, 비어 있으면 앱은 샘플로 동작)
data/snaps/날짜/시각_*.jpg      그 시각 사진
```

## 설치 (10분)

1. GitHub에서 **새 저장소**를 만든다. (Public 권장 — Actions·Pages가 무료)
2. 이 폴더의 파일을 **모두** 올린다. 숨김 폴더 `.github` 가 빠지기 쉬우니, 웹에서 올릴 때 폴더째 끌어다 놓거나
   *Add file → Create new file* 로 `.github/workflows/capture.yml` 을 직접 만들어 내용을 붙여 넣는다.
3. **Settings → Actions → General → Workflow permissions** 에서 *Read and write permissions* 선택 → Save.
4. **Actions** 탭 → 왼쪽 *capture* → *Run workflow*, 입력칸에 `1` 을 적고 실행.
   - 성공하면 `data/data.json` 과 `data/snaps/…` 가 생긴다.
   - 로그에 **"나무 카메라 영상을 받지 못했습니다"** 가 보이면, GitHub 서버에서 원주시 영상(포트 9443)에 접속이 안 되는 것이다.
     이때는 학원 PC·라즈베리파이에서 `python capture.py` 를 매시 실행하는 방법으로 바꿔야 한다. (`pip install pillow numpy`, ffmpeg 필요)
5. **Settings → Pages → Build and deployment → Source: Deploy from a branch**, Branch `main` / `(root)` → Save.
   1~2분 뒤 `https://계정이름.github.io/저장소이름/` 에서 앱이 열린다.

이후 매시(06~18시) 자동으로 한 장씩 쌓이고, 앱은 새로고침할 때마다 최신 기록을 읽는다.

## 선택 설정

| 하고 싶은 것 | 방법 |
|---|---|
| 사람 수·관측평·날씨를 AI가 판독 | 저장소 **Settings → Secrets and variables → Actions → New secret** 에 `ANTHROPIC_API_KEY` 등록. 시간당 사진 1~2장 분량의 API 비용이 든다. |
| 도로 CCTV·잔디밭 *실시간 재생* | 카카오맵이 다른 사이트의 직접 요청을 막아서 작은 중계가 필요하다. `kakao-cctv-worker.js` 를 Cloudflare Worker로 배포하고, `index.html` 위쪽 `SITE.links.roadApi` 에 그 주소(`…workers.dev/?key=4485`)를 넣는다. (정시 캡처는 중계 없이도 된다.) |
| 잔디밭 확대 위치 | `index.html` 의 `lawnCrop` (프레임 비율). 낮 사진을 보고 잔디밭이 보이는 곳으로 맞춘다. |
| 잎을 세는 영역 | `capture.py` 의 `ROI` 와 `index.html` 의 `SITE.roi` 를 **같은 값**으로 맞춘다. 카메라가 움직였으면 여기를 조정. |
| 다른 나무·장소로 바꾸기 | `index.html` 의 `SITE` (이름·좌표·주소·링크), `capture.py` 의 `TREE_HLS`·`KAKAO_CCTV_KEY`·`SEASON` |

## 수치는 이렇게 계산한다

- 사진의 `ROI` 안에서 잎 픽셀을 색상각으로 **샛노랑 / 연노랑 / 초록**으로 센다. 하늘·줄기·그림자는 뺀다.
- **단풍 진척도** = (샛노랑 + 연노랑) ÷ 잎 픽셀. **남은 잎** = 낮 사진의 잎 픽셀 비율을, 지금까지 관측의 상위 10% 값(=잎이 가장 무성했을 때)에 견준 값.
- 야간 적외선(흑백) 사진은 색 판정이 안 되어 직전 낮 값을 이어 쓴다.
- 앱의 *어떻게 재나* 탭이 같은 규칙으로 사진을 칠해 보여 주므로, 숫자가 이상하면 거기서 먼저 확인한다.
- 눈으로 본 단풍과 차이가 날 수 있는 **어림 판독**이다. 광량·카메라 위치가 바뀌면 흔들린다.

## 알아 둘 것

- GitHub의 예약 실행은 정각보다 몇~수십 분 늦을 수 있다. 30분 넘게 늦으면 그 시각은 다음 시각으로 기록된다.
- 사진은 하루 26장(나무+도로) 안팎, 약 1MB. 시즌 6주면 40~50MB.
- 공개 저장소에는 사진이 그대로 공개된다. 원주시·국토교통부 영상의 이용 조건을 확인하고 쓸 것.
- 저장소에 60일간 활동이 없으면 GitHub가 예약 실행을 멈춘다.
