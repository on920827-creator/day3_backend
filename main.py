"""
main.py — 제주 미세먼지 백엔드 (FastAPI)

   공공데이터 API ──① 받기──▶ FastAPI ──② 가공──③ 예측──▶ ④ Supabase 저장
                                   ▲
   Vercel(React) ── 결과만 요청 ───┘   (키는 전부 Railway 서버 안에만)

Railway Variables
  SUPABASE_URL, SUPABASE_SECRET_KEY   Supabase 연결 (없으면 메모리 임시 저장)
  DATA_GO_KR_KEY                      공공데이터포털 인증키 (없으면 연습 데이터)
  ADMIN_TOKEN                         /collect 를 아무나 못 누르게 하는 암호
  FRONT_ORIGINS                       Vercel 주소 (쉼표로 여러 개)
  SIDO_NAME=제주  COLLECT_MINUTES=60  AUTO_COLLECT=1  DEMO_MODE=0
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

try:                                   # 로컬 실행 때만 .env 를 읽는다 (Railway 에서는 Variables 사용)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import collect
import db
import predict
import story

log = logging.getLogger("uvicorn.error")

DATA_KEY = db.env("DATA_GO_KR_KEY")
SIDO = db.env("SIDO_NAME", "제주")
ADMIN_TOKEN = db.env("ADMIN_TOKEN")
DEMO = db.env("DEMO_MODE", "0") == "1" or not DATA_KEY
SOURCE = "demo" if DEMO else "airkorea"
AUTO = db.env("AUTO_COLLECT", "1") == "1"
WARNINGS: list[str] = []                 # 설정이 이상해도 죽지 않고 여기에 적어 /health 에 보여 준다
try:
    MINUTES = max(1, int(db.env("COLLECT_MINUTES", "60")))
except ValueError:
    MINUTES = 60
    WARNINGS.append("COLLECT_MINUTES 가 숫자가 아니라서 60 으로 처리했습니다")
FRONT_ORIGINS = [o.strip().strip('"').strip("'").rstrip("/")
                 for o in db.env("FRONT_ORIGINS").split(",") if o.strip()]

store = db.get_store()


# ─────────────── 수집 한 번 = 받기 → 가공 → 저장 → 기록 ───────────────
def run_collect(hours: int = 1) -> dict:
    items = collect.fake_raw(hours) if DEMO else collect.fetch_raw(SIDO, DATA_KEY)
    rows, stats = collect.clean(items, SIDO, SOURCE)
    saved = store.save_readings(rows)
    entry = {"ran_at": datetime.now(timezone.utc).isoformat(), "source": SOURCE,
             **stats, "saved": saved}
    store.save_log(entry)
    log.info("collect %s", entry)
    return entry


async def auto_loop():
    """서버가 켜져 있는 동안 COLLECT_MINUTES 마다 자동 수집 (브라우저가 꺼져 있어도!)"""
    # 연습 모드에서 DB가 비어 있으면 예측을 바로 볼 수 있게 72시간치를 한 번 채운다
    if DEMO and not store.recent(SOURCE, 1):
        await asyncio.to_thread(run_collect, 72)
    while True:
        try:
            await asyncio.to_thread(run_collect)
        except Exception:
            log.exception("자동 수집 실패")
        await asyncio.sleep(MINUTES * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(auto_loop()) if AUTO else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="제주 미세먼지 백엔드", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=FRONT_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(story.router)       # 설문대할망 스토리 웹의 'AI 장면 만들기' (ANTHROPIC_API_KEY 필요)


@app.get("/")
def home():
    return {"service": "제주 미세먼지 백엔드", "mode": SOURCE, "docs": "/docs"}


@app.get("/health")
def health():
    names = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "DATA_GO_KR_KEY", "ADMIN_TOKEN", "FRONT_ORIGINS"]
    missing = [k for k in names if not db.env(k)]
    problems = list(WARNINGS)
    if store.error:
        problems.append(store.error)
    try:
        store.ping()
    except Exception as e:
        problems.append(f"DB 연결/테이블 확인 실패: {str(e)[:150]}")
    return {"ok": not problems, "mode": SOURCE, "store": store.kind,
            "auto_collect_minutes": MINUTES if AUTO else None,
            "missing": missing,                       # 아직 안 넣은 변수 이름
            "problems": problems,                     # 서버가 대신 처리한 설정 문제
            "front_origins": FRONT_ORIGINS,           # CORS 로 허용 중인 주소
            "checked_at": datetime.now(timezone.utc).isoformat()}


@app.post("/collect")
def collect_now(x_admin_token: str = Header(default=""),
                hours: int = Query(1, ge=1, le=168, description="연습 모드에서만: 몇 시간치 만들지")):
    """지금 바로 한 번 수집 (Swagger /docs 에서 Try it out)"""
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Railway Variables 에 ADMIN_TOKEN 을 먼저 넣으세요")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "x-admin-token 이 틀렸습니다")
    try:
        return run_collect(hours if DEMO else 1)
    except Exception as e:
        raise HTTPException(502, str(e))


def _latest_rows():
    rows = store.recent(SOURCE)
    seen, latest = set(), []
    for r in rows:                     # 시각 내림차순 → 측정소별 첫 행이 최신
        if r["station"] not in seen:
            seen.add(r["station"])
            latest.append(r)
    return latest


@app.get("/air/latest")
def air_latest():
    rows = _latest_rows()
    rows.sort(key=lambda r: r["pm10"] or 0, reverse=True)
    return [{"station": r["station"], "time": db.kst(r["data_time"]),
             "pm10": r["pm10"], "pm10_grade": r["pm10_grade"],
             "pm25": r["pm25"], "pm25_grade": r["pm25_grade"]} for r in rows]


@app.get("/air/summary")
def air_summary():
    rows = _latest_rows()
    pm10s = [r["pm10"] for r in rows if r["pm10"] is not None]
    pm25s = [r["pm25"] for r in rows if r["pm25"] is not None]
    worst = max(rows, key=lambda r: r["pm10"] or 0) if rows else None
    logs = store.logs(1)
    return {
        "mode": SOURCE,
        "stations": len(rows),
        "avg_pm10": round(sum(pm10s) / len(pm10s)) if pm10s else None,
        "avg_pm25": round(sum(pm25s) / len(pm25s)) if pm25s else None,
        "avg_pm10_grade": collect.grade_pm10(round(sum(pm10s) / len(pm10s))) if pm10s else None,
        "worst_station": worst and {"station": worst["station"], "pm10": worst["pm10"]},
        "last_collect": logs[0] if logs else None,
    }


@app.get("/air/predict")
def air_predict(station: str, hours: int = Query(1, ge=1, le=24, description="몇 시간 뒤까지 (24 = 내일 이맘때)")):
    hist = store.history(SOURCE, station)
    if not hist:
        raise HTTPException(404, f"'{station}' 측정소 데이터가 없습니다")
    return {"station": station, **predict.predict_next(hist, hours)}


@app.get("/logs")
def logs():
    return store.logs()
