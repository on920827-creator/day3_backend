"""
predict.py — ③ 머신러닝: 다음 1시간 미세먼지 예측

DB에 쌓인 '지난 몇 시간 값'을 보고 '다음 시간 값'을 맞히도록
선형회귀(scikit-learn LinearRegression)를 그 자리에서 학습시킨다.
  입력(X) = 직전 3시간 PM10 (+ 하루가 쌓이면 어제 같은 시간)   →   정답(y) = 그다음 시간 PM10
"""
from sklearn.linear_model import LinearRegression

from collect import grade_pm10

LAGS = 3          # 직전 몇 시간을 볼지
SEASON = 24       # 하루 주기: 어제 같은 시간 값
DAILY_MIN_ROWS = 8  # 학습 예시가 이만큼 되면 하루 주기 입력을 추가
MIN_POINTS = 12   # 이만큼 쌓이면 학습 예측, 적으면 간단 추정


def predict_next(history: list[dict], steps: int = 1) -> dict:
    vals = [h["pm10"] for h in history if h.get("pm10") is not None]
    if not vals:
        return {"ready": False, "points": 0, "message": "아직 쌓인 데이터가 없어요. 잠시 뒤 다시 눌러 주세요"}
    steps = max(1, steps)
    if len(vals) < MIN_POINTS:
        # 데이터가 적을 때: 학습 대신 '최근 값의 평균'으로 간단 추정 (정확도는 낮음)
        recent = vals[-LAGS:]
        est = max(0, round(sum(recent) / len(recent)))
        spread = round(sum(abs(v - sum(vals) / len(vals)) for v in vals) / len(vals), 1)
        return {"ready": True, "simple": True, "hours": steps, "path": [est] * steps,
                "points": len(vals), "recent": vals[-12:], "next_pm10": est,
                "next_grade": grade_pm10(est), "avg_error": spread,
                "model": f"간단 추정(최근 {len(recent)}개 평균) — 데이터 {MIN_POINTS}개부터 학습 예측"}

    # '어제 같은 시간' 값도 입력에 넣을 만큼 쌓였으면(약 1.3일) 하루 주기를 함께 학습
    daily = len(vals) - SEASON >= DAILY_MIN_ROWS

    def feat(series, i):                      # i 번째 값을 맞히기 위한 입력
        f = series[i - LAGS:i]                # 직전 3시간
        return f + [series[i - SEASON]] if daily else f   # + 24시간 전(어제 같은 시간)

    start = max(LAGS, SEASON) if daily else LAGS
    X = [feat(vals, i) for i in range(start, len(vals))]
    y = vals[start:]

    # 마지막 몇 개는 시험용으로 빼서 '얼마나 틀리는지' 먼저 잰다
    test = max(2, min(6, len(X) // 4))
    model = LinearRegression().fit(X[:-test], y[:-test])
    errors = [abs(p - t) for p, t in zip(model.predict(X[-test:]), y[-test:])]
    mae = sum(errors) / len(errors)

    # 전체로 다시 학습 → 한 시간씩 steps 번 이어서 예측 (예측값을 다음 입력으로 사용)
    model = LinearRegression().fit(X, y)
    window = list(vals)
    lo, hi = min(vals) * 0.5, max(vals) * 1.5
    path = []
    for _ in range(max(1, steps)):
        nv = float(model.predict([feat(window, len(window))])[0])
        nv = min(max(nv, lo), hi)           # 이어서 예측하다 터무니없이 벗어나지 않게 관측 범위로 제한
        path.append(round(nv))
        window.append(nv)
    nxt = path[-1]
    return {
        "hours": len(path),
        "path": path,
        "ready": True,
        "points": len(vals),
        "recent": vals[-12:],
        "next_pm10": nxt,
        "next_grade": grade_pm10(nxt),
        "avg_error": round(mae, 1),
        "daily": daily,
        "model": f"LinearRegression(직전 {LAGS}시간" + (" + 어제 같은 시간" if daily else "") + f" → 다음 1시간, {len(path)}시간 뒤까지 반복)",
    }
