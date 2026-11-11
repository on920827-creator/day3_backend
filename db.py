"""
db.py — ④ 저장: Supabase(진짜 DB)

SUPABASE_URL / SUPABASE_SECRET_KEY 가 Railway Variables에 있으면 Supabase에 저장하고,
아직 없으면 서버 메모리에 임시 저장한다(재시작하면 사라짐). 그래서 변수를 넣기 전
첫 배포도 죽지 않고 /health 에서 무엇이 빠졌는지 알려 준다.
"""
import os
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def env(name: str, default: str = "") -> str:
    """환경변수를 읽되 앞뒤 공백과 따옴표(" ')를 지워서 돌려준다 (Variables 입력 실수 방지)."""
    v = os.getenv(name, default) or default
    return v.strip().strip('"').strip("'").strip()


def kst(ts: str) -> str:
    """DB 시각(UTC 등) → '2026-11-10 14:00' (한국 시간)"""
    return datetime.fromisoformat(ts).astimezone(KST).strftime("%Y-%m-%d %H:%M")


class SupabaseStore:
    kind = "supabase"
    error = None

    def __init__(self, url, key):
        from supabase import create_client
        self.sb = create_client(url, key)

    def ping(self):
        """DB 에 실제로 닿는지 확인 (테이블이 없거나 주소·키가 틀리면 예외)"""
        self.sb.table("air_readings").select("id").limit(1).execute()

    def save_readings(self, rows):
        if not rows:
            return 0
        # 같은 측정소·같은 시각이면 새로 넣지 않고 덮어쓴다(중복 방지)
        res = (self.sb.table("air_readings")
               .upsert(rows, on_conflict="source,station,data_time").execute())
        return len(res.data or [])

    def save_log(self, log):
        self.sb.table("collect_logs").insert(log).execute()

    def recent(self, source, limit=300):
        res = (self.sb.table("air_readings").select("*").eq("source", source)
               .order("data_time", desc=True).limit(limit).execute())
        return res.data

    def history(self, source, station, limit=72):
        res = (self.sb.table("air_readings").select("data_time,pm10,pm25")
               .eq("source", source).eq("station", station)
               .order("data_time", desc=True).limit(limit).execute())
        return list(reversed(res.data))

    def logs(self, limit=20):
        res = (self.sb.table("collect_logs").select("*")
               .order("ran_at", desc=True).limit(limit).execute())
        return res.data


class MemoryStore:
    kind = "memory(임시)"
    error = None            # Supabase 연결에 실패해서 메모리로 켜졌다면 이유가 들어간다

    def __init__(self):
        self.rows = {}
        self._logs = []

    def ping(self):
        pass

    def save_readings(self, rows):
        for r in rows:
            self.rows[(r["source"], r["station"], r["data_time"])] = r
        return len(rows)

    def save_log(self, log):
        self._logs.append(log)

    def recent(self, source, limit=300):
        rs = [r for r in self.rows.values() if r["source"] == source]
        return sorted(rs, key=lambda r: r["data_time"], reverse=True)[:limit]

    def history(self, source, station, limit=72):
        rs = [r for r in self.rows.values() if r["source"] == source and r["station"] == station]
        return sorted(rs, key=lambda r: r["data_time"])[-limit:]

    def logs(self, limit=20):
        return list(reversed(self._logs))[:limit]


def get_store():
    url = env("SUPABASE_URL")
    key = env("SUPABASE_SECRET_KEY")
    if url and key:
        if not url.startswith("http"):
            url = "https://" + url                       # https:// 를 빼먹은 경우
        url = url.rstrip("/").removesuffix("/rest/v1").rstrip("/")
        try:
            return SupabaseStore(url, key)
        except Exception as e:                           # 연결 실패해도 서버는 죽지 않는다
            s = MemoryStore()
            s.error = f"Supabase 연결 실패: {type(e).__name__}: {e}"
            return s
    return MemoryStore()
