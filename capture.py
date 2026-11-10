#!/usr/bin/env python3
"""매시 한 번 실행: 영상에서 한 프레임씩 받아 저장하고, 단풍·잎 수치를 계산해 data/data.json 에 쌓는다.

환경변수(모두 선택)
  TREE_HLS          나무 카메라 HLS 주소 (기본: 원주시 중계). 로컬 파일 경로도 가능(시험용)
  KAKAO_CCTV_KEY    카카오맵 CCTV 키 (기본 4485 = 국도42 반계IC)
  ROAD_URL          도로 영상 주소를 직접 지정(카카오 API를 건너뜀, 시험용)
  DATA_DIR          저장 폴더 (기본 data)
  FORCE=1           관측 시간대(06~18시) 밖에서도, 이미 기록한 시각에도 다시 실행
  SLOT_HOUR / SLOT_DATE  기록할 시각·날짜를 강제로 지정 (시험용)
  ANTHROPIC_API_KEY 있으면 사진을 AI에게 보여 사람 수·관측평·날씨를 받아 적는다
  AI_MODEL          AI 모델 (기본 claude-haiku-5-5)
"""
import base64, json, os, subprocess, sys, tempfile, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image

KST = timezone(timedelta(hours=9))
TREE_HLS = os.environ.get("TREE_HLS", "https://live.wonju.go.kr:9443/live/CH01.stream_480p/playlist.m3u8")
KAKAO_KEY = os.environ.get("KAKAO_CCTV_KEY", "4485")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
SEASON = {"start": "2026-10-15", "end": "2026-11-30"}
HOURS = range(6, 19)                     # 관측 시간대 (KST, 6~18시)
ROI = (0.03, 0.05, 0.97, 0.78)           # 나무 사진에서 잎을 세는 영역 (x0,y0,x1,y1 비율). 아래쪽 땅은 뺀다
JPEG_W, JPEG_Q = 640, 72
LEAF_H0 = 38                              # 잎으로 치는 색상각 하한(°)


# ───────────────────────── 프레임 받기 ─────────────────────────
def grab_frame(src: str, out: Path, tries: int = 2) -> bool:
    for k in range(tries):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-rw_timeout", "15000000",
                 "-i", src, "-frames:v", "1", "-q:v", "2", str(out)],
                check=True, timeout=60)
            if out.exists() and out.stat().st_size > 3000:
                return True
        except Exception as e:                       # noqa: BLE001
            print(f"  프레임 받기 실패({k + 1}/{tries}): {e}", file=sys.stderr)
    return False


def kakao_live_url(key: str) -> str:
    req = urllib.request.Request(
        f"https://map.kakao.com/api/cctvs/url/{key}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": f"https://map.kakao.com/?cctv={key}",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        j = json.load(r)
    url = j.get("liveUrl") or ""
    if not url:
        raise RuntimeError("카카오 응답에 liveUrl 이 없음")
    return url.replace("http:", "https:", 1)


# ───────────────────────── 판독 (앱의 '어떻게 재나'와 같은 규칙) ─────────────────────────
def classify(rgb: np.ndarray):
    """rgb: HxWx3 uint8 → (leaf, yellow, pale, green) 불리언 배열.
    앱(index.html의 drawHow)과 같은 계산식·같은 경계값을 쓴다 — 한쪽만 고치면 판독이 어긋난다."""
    a = rgb.astype(np.float64)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    d = mx - mn
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.where(d == 0, 0.0, np.where(mx == R, ((G - B) / d) % 6,
                     np.where(mx == G, (B - R) / d + 2, (R - G) / d + 4))) * 60.0
        s = np.where(mx > 0, d / mx, 0.0)
    v = mx / 255.0
    sky = (B > R) & (B >= G - 8) & (v > 0.67)
    leaf = (~sky) & (s >= 0.22) & (v >= 0.20) & (h >= LEAF_H0) & (h <= 165)   # 갈색 줄기(≈20~35°)는 제외
    yellow = leaf & (h < 62) & (s >= 0.70)
    pale = leaf & (((h < 62) & (s < 0.70)) | ((h >= 62) & (h < 80)))
    green = leaf & (h >= 80)
    return leaf, yellow, pale, green


def is_dark(rgb: np.ndarray) -> bool:
    """야간 적외선(흑백) 화면이거나 아주 어두우면 True — 색 판정 불가"""
    a = rgb.astype(np.int16)
    chroma = float(np.mean(np.abs(a[..., 0] - a[..., 1]) + np.abs(a[..., 1] - a[..., 2])))
    return chroma < 2.0 or float(a.max(axis=2).mean()) / 255.0 < 0.10


def analyze(img: Image.Image) -> dict:
    img = img.convert("RGB")
    w = 320
    img = img.resize((w, max(1, round(img.height * w / img.width))))
    full = np.asarray(img)
    dark = is_dark(full)
    x0, y0, x1, y1 = ROI
    H, W = full.shape[:2]
    roi = full[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
    out = {"dark": bool(dark), "fol": None, "yel": None, "leaf": None, "stages": None, "sd": None}
    if dark:
        return out
    leaf, yel, pale, green = classify(roi)
    n_leaf = int(leaf.sum())
    out["leaf"] = round(n_leaf / leaf.size, 4)
    if n_leaf < 0.004 * leaf.size:                     # 잎이 거의 없음 — 색 비율은 의미 없음
        return out
    ny, npl, ng = int(yel.sum()), int(pale.sum()), int(green.sum())
    out["fol"] = round((ny + npl) / n_leaf * 100, 1)
    out["yel"] = round(ny / n_leaf * 100, 1)
    out["stages"] = [round(ny / n_leaf * 100, 1), round(npl / n_leaf * 100, 1), round(ng / n_leaf * 100, 1)]
    # 구역 편차: 3x2 칸에서 칸별 단풍 비율의 표준편차 (작을수록 고르게 물듦)
    zones = []
    zh, zw = leaf.shape[0] // 2, leaf.shape[1] // 3
    for r in range(2):
        for c in range(3):
            sl = (slice(r * zh, (r + 1) * zh), slice(c * zw, (c + 1) * zw))
            n = int(leaf[sl].sum())
            if n >= 0.01 * zh * zw:
                zones.append((int(yel[sl].sum()) + int(pale[sl].sum())) / n * 100)
    out["sd"] = round(float(np.std(zones)), 1) if len(zones) >= 3 else None
    return out


# ───────────────────────── (선택) AI 판독 ─────────────────────────
def ai_read(paths: list[Path]) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        content = []
        for p in paths:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.b64encode(p.read_bytes()).decode()}})
        content.append({"type": "text", "text": (
            "첫 사진은 은행나무 정면, 둘째 사진(있으면)은 도로 CCTV다. JSON 한 줄로만 답해라: "
            '{"people_tree":정수,"people_lawn":정수,"weather":"맑음|흐림|비|눈|안개 중 하나",'
            '"comment":"관측평 한 문장(40자 이내, 한국어)"}. 사람이 없으면 0.')})
        body = json.dumps({"model": os.environ.get("AI_MODEL", "claude-haiku-5-5"), "max_tokens": 300,
                           "messages": [{"role": "user", "content": content}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = json.load(r)["content"][0]["text"]
        j = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        return {"pt": int(j.get("people_tree", 0)), "pl": int(j.get("people_lawn", 0)),
                "weather": str(j.get("weather", ""))[:8], "comment": str(j.get("comment", ""))[:80]}
    except Exception as e:                           # noqa: BLE001
        print(f"  AI 판독 실패(건너뜀): {e}", file=sys.stderr)
        return None


# ───────────────────────── 기록 ─────────────────────────
def percentile(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round((len(vals) - 1) * p)))]


def recompute(records: list[dict]) -> None:
    """남은 잎(rem)은 지금까지 낮 사진의 '잎 픽셀 비율' 상위 10% 값을 100%로 놓고 상대값으로 계산.
    야간(색 판정 불가) 기록은 직전 낮 값을 이어 쓴다(carried)."""
    records.sort(key=lambda r: r["ts"])
    leafs = [r["leaf"] for r in records if not r["dark"] and r.get("leaf") is not None]
    base = percentile(leafs, 0.9) if leafs else None
    prev = {"fol": 0.0, "yel": 0.0, "rem": 100.0, "stages": [0, 0, 100], "sd": None}
    for r in records:
        if not r["dark"] and r.get("leaf") is not None and base:
            r["rem"] = round(max(0.0, min(100.0, r["leaf"] / base * 100)), 1)
        for k in ("fol", "yel", "stages", "sd", "rem"):
            if r.get(k) is None:
                r[k] = prev[k]
                r["carried"] = True
        for k in prev:
            prev[k] = r[k]


def main() -> int:
    now = datetime.now(KST)
    if os.environ.get("SLOT_DATE"):                  # 시험용: 날짜를 지정해 과거 기록처럼 쌓는다
        now = datetime.fromisoformat(f"{os.environ['SLOT_DATE']}T{int(os.environ.get('SLOT_HOUR', 12)):02d}:05:00+09:00")
    hour = int(os.environ["SLOT_HOUR"]) if os.environ.get("SLOT_HOUR") else (now.hour + (1 if now.minute >= 30 else 0))
    force = os.environ.get("FORCE") == "1"
    if hour not in HOURS and not force:
        print(f"{hour}시는 관측 시간대(06~18시)가 아니라 건너뜀")
        return 0
    date = now.strftime("%Y-%m-%d") if hour < 24 else (now + timedelta(days=1)).strftime("%Y-%m-%d")
    rid = f"{date.replace('-', '')}-{hour:02d}00"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    jpath = DATA_DIR / "data.json"
    db = json.loads(jpath.read_text(encoding="utf8")) if jpath.exists() else {}
    records = db.get("records", [])
    if any(r["id"] == rid for r in records) and not force:
        print(f"{rid} 는 이미 기록됨")
        return 0

    snap_dir = DATA_DIR / "snaps" / date
    snap_dir.mkdir(parents=True, exist_ok=True)
    img_paths, saved = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 1) 나무 카메라 (필수)
        print("나무 카메라 받는 중…")
        if not grab_frame(TREE_HLS, tmp / "tree.jpg"):
            print("나무 카메라 영상을 받지 못했습니다.", file=sys.stderr)
            return 1
        # 2) 도로 CCTV (선택 — 실패해도 계속)
        print("도로 CCTV 받는 중…")
        try:
            road_src = os.environ.get("ROAD_URL") or kakao_live_url(KAKAO_KEY)
            if not grab_frame(road_src, tmp / "road.jpg"):
                print("  도로 CCTV 프레임을 받지 못함(건너뜀)", file=sys.stderr)
        except Exception as e:                       # noqa: BLE001
            print(f"  도로 CCTV 실패(건너뜀): {e}", file=sys.stderr)

        for name in ("tree", "road"):
            src = tmp / f"{name}.jpg"
            if not src.exists():
                continue
            im = Image.open(src).convert("RGB")
            if name == "tree":
                metrics = analyze(im)
            if im.width > JPEG_W:
                im = im.resize((JPEG_W, round(im.height * JPEG_W / im.width)))
            dst = snap_dir / f"{hour:02d}00_{name}.jpg"
            im.save(dst, "JPEG", quality=JPEG_Q, optimize=True)
            img_paths[name] = dst
            saved[name] = f"snaps/{date}/{dst.name}"

    ai = ai_read([img_paths[k] for k in ("tree", "road") if k in img_paths])
    rec = {"id": rid, "ts": now.isoformat(timespec="seconds"), "date": date, "h": hour, **metrics,
           "rem": None, "pt": ai["pt"] if ai else None, "pl": ai["pl"] if ai else None,
           "weather": ai["weather"] if ai else None, "comment": ai["comment"] if ai else None, "img": saved}
    records = [r for r in records if r["id"] != rid] + [rec]
    recompute(records)
    db = {"updated": now.isoformat(timespec="seconds"), "season": SEASON, "records": records}
    jpath.write_text(json.dumps(db, ensure_ascii=False, separators=(",", ":")), encoding="utf8")
    r = next(x for x in records if x["id"] == rid)
    print(f"기록 {rid}: dark={r['dark']} 단풍={r['fol']}% 남은잎={r['rem']}% 노랑={r['yel']}% sd={r['sd']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
