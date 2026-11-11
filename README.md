[db.py](https://github.com/user-attachments/files/34670000/db.py)
[main.py](https://github.com/user-attachments/files/34670001/main.py)[predict.py](https://github.com/user-attachments/files/34670003/predict.py)
[predict.py](https://github.com/user-attachments/files/34670002/predict.py)
"""
predict.py — ③ 머신러닝: 다음 1시간 미세먼지 예측

DB에 쌓인 '지난 몇 시간 값'을 보고 '다음 시간 값'을 맞히도록
선형회귀(scikit-learn LinearRegression)를 그 자리에서 학습시킨다.
  입력(X) = 직전 3시간 PM10   →   정답(y) = 그다음 시간 PM10
"""
from sklearn.linear_model import LinearRegression

from collect import grade_pm10

LAGS = 3          # 직전 몇 시간을 볼지
MIN_POINTS = 12   # 최소 몇 개가 쌓여야 학습할지


def predict_next(history: list[dict], steps: int = 1) -> dict:
    vals = [h["pm10"] for h in history if h.get("pm10") is not None]
    if len(vals) < MIN_POINTS:
        return {"ready": False, "points": len(vals),
                "message": f"데이터가 {MIN_POINTS}개 이상 쌓여야 예측할 수 있어요 (지금 {len(vals)}개)"}

    # 학습 문제 만들기: [t-3, t-2, t-1] → t
    X = [vals[i - LAGS:i] for i in range(LAGS, len(vals))]
    y = vals[LAGS:]

    # 마지막 6개는 시험용으로 빼서 '얼마나 틀리는지' 먼저 잰다
    test = 6
    model = LinearRegression().fit(X[:-test], y[:-test])
    errors = [abs(p - t) for p, t in zip(model.predict(X[-test:]), y[-test:])]
    mae = sum(errors) / len(errors)

    # 전체로 다시 학습 → 한 시간씩 steps 번 이어서 예측 (예측값을 다음 입력으로 사용)
    model = LinearRegression().fit(X, y)
    window = list(vals[-LAGS:])
    path = []
    for _ in range(max(1, steps)):
        nv = max(0.0, float(model.predict([window[-LAGS:]])[0]))
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
        "model": f"LinearRegression(직전 {LAGS}시간 → 다음 1시간, {len(path)}시간 뒤까지 반복)",
    }
