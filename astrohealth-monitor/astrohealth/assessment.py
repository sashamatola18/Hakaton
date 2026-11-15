"""Оцінка стану астронавта за показниками та рекомендовані дії.

УВАГА: порогові значення навчальні й ілюстративні, не є медичними нормами.
"""
OK, WARN, CRIT = 0, 1, 2
LEVELS = {OK: "норма", WARN: "увага", CRIT: "критично"}

# ключ: (назва, одиниця, warn_мін, warn_макс, crit_мін, crit_макс)
# Пороги взято з опублікованих норм (див. SOURCES нижче та README). «Увага» спрацьовує,
# коли значення менше warn_мін або більше warn_макс; «критично» — так само для crit.
METRICS = {
    "heart_rate": ("Пульс", "уд/хв", 50, 100, 40, 130),
    "spo2": ("SpO₂", "%", 95, None, 90, None),
    "systolic": ("Тиск (сист.)", "мм рт.ст.", 90, 139, 80, 180),
    "diastolic": ("Тиск (діаст.)", "мм рт.ст.", 60, 89, 50, 120),
    "temperature": ("Температура", "°C", 36.0, 37.5, 35.0, 39.0),
    "resp_rate": ("Дихання", "вд/хв", 12, 20, 8, 30),
    "glucose": ("Глюкоза", "ммоль/л", 3.9, 10.0, 3.0, 13.9),
    "co2": ("CO₂ у кабіні", "мм рт.ст.", None, 3.0, None, 5.3),
    "radiation": ("Радіація за добу", "мЗв", None, 2.0, None, 10.0),
    "sleep": ("Сон", "год", 6, None, 4, None),
}
# Звідки взято норми (коротко; посилання — у README)
SOURCES = {
    "heart_rate": "Норма дорослого у спокої 60–100 уд/хв, у тренованих людей буває нижче. Пороги тривоги — вибір проєкту.",
    "spo2": "Норма 95–100 %. Нижче 90 % — небезпечна нестача кисню.",
    "systolic": "Класифікація AHA/ACC: гіпертензія 2 стадії від 140, криза понад 180. Нижче 90 — гіпотензія.",
    "diastolic": "Класифікація AHA/ACC: гіпертензія 2 стадії від 90, криза понад 120.",
    "temperature": "Норма приблизно 36,1–37,2 °C. Нижче 35 °C — переохолодження.",
    "resp_rate": "Норма дорослого у спокої 12–20 вдихів за хвилину.",
    "glucose": "ADA: гіпоглікемія 1 рівня нижче 3,9 ммоль/л, 2 рівня нижче 3,0. Після їжі — до 10 ммоль/л.",
    "co2": "Стандарт NASA-STD-3001: середнє за годину до 3 мм рт.ст.; допустима межа SMAC 5,3 мм рт.ст.",
    "radiation": "На МКС 0,2–0,5 мЗв за добу, у далекому космосі у 2–3 рази більше. Пороги тривоги — вибір проєкту.",
    "sleep": "Дорослим рекомендують 7–9 годин сну. Пороги тривоги — вибір проєкту.",
}

# Межі правдоподібності для ручного введення (захист від одруківок): ключ: (мін, макс)
LIMITS = {"heart_rate": (20, 250), "spo2": (50, 100), "systolic": (50, 260), "diastolic": (30, 160),
          "temperature": (30, 43), "resp_rate": (2, 60), "glucose": (1, 35), "co2": (0, 30),
          "radiation": (0, 1000), "sleep": (0, 24)}

# ключ: {сторона: (дія при "увага", дія при "критично")}
ACTIONS = {
    "heart_rate": {
        "low": ("Відпочиньте, повторіть вимір через 10 хв.", "Припиніть роботу, лягайте, негайно зв'яжіться з лікарем польоту."),
        "high": ("Зупиніться, дихайте повільно 5 хв, повторіть вимір.", "Негайно припиніть навантаження і зв'яжіться з лікарем польоту.")},
    "spo2": {"low": ("Перевірте датчик і вентиляцію модуля, дихайте глибоко, повторіть вимір.",
                     "Підключіть кисень, перейдіть у модуль зі свіжим повітрям, викличте лікаря польоту.")},
    "systolic": {
        "low": ("Сядьте, випийте води, повторіть вимір через 15 хв.", "Лягайте, підніміть ноги, зв'яжіться з лікарем польоту."),
        "high": ("Відпочиньте, уникайте кофеїну, повторіть вимір.", "Припиніть роботу, зв'яжіться з лікарем польоту.")},
    "diastolic": {
        "low": ("Сядьте, випийте води, повторіть вимір через 15 хв.", "Лягайте, підніміть ноги, зв'яжіться з лікарем польоту."),
        "high": ("Відпочиньте, повторіть вимір через 15 хв.", "Припиніть роботу, зв'яжіться з лікарем польоту.")},
    "glucose": {
        "low": ("З'їжте 15 г швидких вуглеводів, повторіть вимір через 15 хв.", "Негайно прийміть глюкозу, не залишайтеся наодинці, викличте лікаря польоту."),
        "high": ("Пийте воду, повторіть вимір через годину.", "Зв'яжіться з лікарем польоту: дуже високий рівень глюкози.")},
    "temperature": {
        "low": ("Утеплитесь, перевірте температуру в модулі.", "Зв'яжіться з лікарем польоту: ризик переохолодження."),
        "high": ("Відпочиньте, пийте воду, перевірте охолодження.", "Ізолюйтеся від екіпажу, зв'яжіться з лікарем польоту: можлива інфекція.")},
    "resp_rate": {
        "low": ("Дихайте глибше, оцініть самопочуття.", "Негайно зв'яжіться з лікарем польоту."),
        "high": ("Припиніть навантаження, дихайте повільно, перевірте CO₂.", "Перевірте CO₂/O₂ у модулі та негайно зв'яжіться з лікарем польоту.")},
    "co2": {"high": ("Перевірте систему видалення CO₂ і вентиляцію, зменште навантаження.",
                     "Увімкніть резервний скрубер, перейдіть у безпечний модуль, повідомте ЦУП.")},
    "radiation": {"high": ("Зменште час поза укриттям, перевірте дозиметр.",
                           "Негайно перейдіть в радіаційне укриття та повідомте ЦУП.")},
    "sleep": {"low": ("Заплануйте відновлювальний сон, обмежте кофеїн.",
                      "Звільніть від складних операцій, потрібен огляд лікаря польоту.")},
}


def classify(key, value, table=None):
    """Повертає (рівень, сторона) для одного показника."""
    _, _, wl, wh, cl, ch = (table or METRICS)[key]
    if cl is not None and value < cl: return CRIT, "low"
    if ch is not None and value > ch: return CRIT, "high"
    if wl is not None and value < wl: return WARN, "low"
    if wh is not None and value > wh: return WARN, "high"
    return OK, None


def evaluate(readings):
    """Оцінює набір показників → загальний стан, список показників і дії."""
    items, actions = [], []
    for key, value in readings.items():
        if key not in METRICS or value is None:
            continue
        level, side = classify(key, value)
        name, unit = METRICS[key][:2]
        items.append({"key": key, "name": name, "unit": unit, "value": value,
                      "level": level, "side": side, "label": LEVELS[level]})
        if level:
            actions.append({"level": level, "metric": name, "text": ACTIONS[key][side][level - 1]})
    overall = max((i["level"] for i in items), default=OK)
    if overall == WARN and sum(i["level"] == WARN for i in items) >= 3:
        overall = CRIT
        actions.append({"level": CRIT, "metric": "Комбінований ризик",
                        "text": "Кілька показників поза нормою одночасно: зв'яжіться з лікарем польоту."})
    actions.sort(key=lambda a: -a["level"])
    if overall == OK:
        actions = [{"level": OK, "metric": "Загальне",
                    "text": "Усе в нормі. Продовжуйте за розкладом: вода, тренування, сон."}]
    return {"overall": overall, "label": LEVELS[overall], "items": items, "actions": actions}


def _slope(ys):
    n = len(ys)
    mx, my = (n - 1) / 2, sum(ys) / n
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / sum((i - mx) ** 2 for i in range(n))


def detect_trends(history, window=10, horizon=10):
    """Раннє попередження: показник рухається до гіршої зони, хоча зараз ще в межах.

    history — список словників показників (від старих до нових).
    Лінійний тренд за останні `window` вимірів екстраполюється на `horizon` кроків.
    Щоб не плутати тенденцію з одноразовим стрибком (наприклад, одужання після нападу),
    рух має тривати й у найсвіжіших вимірах: нахил за останню половину вікна мусить мати
    той самий знак і бути не меншим за половину загального, а сама пряма — добре описувати
    дані (R² від 0,7), щоб випадковий шум датчика не здавався тенденцією.
    """
    out = []
    for key, (name, *_rest) in METRICS.items():
        ys = [r[key] for r in history[-window:] if r.get(key) is not None]
        n = len(ys)
        if n < 6:
            continue
        slope, recent = _slope(ys), _slope(ys[n // 2:])
        if slope == 0 or slope * recent <= 0 or abs(recent) < abs(slope) / 2:
            continue
        mean = sum(ys) / n   # тенденція має пояснювати більшість розкиду, інакше це просто шум датчика
        total = sum((y - mean) ** 2 for y in ys)
        resid = sum((y - (mean + slope * (i - (n - 1) / 2))) ** 2 for i, y in enumerate(ys))
        if total == 0 or 1 - resid / total < 0.7:
            continue
        future = classify(key, ys[-1] + slope * horizon)[0]
        if future > classify(key, ys[-1])[0]:
            word = "зростає" if slope > 0 else "спадає"
            out.append({"level": future, "metric": name,
                        "text": f"{word} і найближчим часом вийде за норму. Дійте завчасно."})
    return out


CABIN = {  # параметри кабіни: (назва, одиниця, warn_мін, warn_макс, crit_мін, crit_макс)
    "temp": ("Температура", "°C", 18, 27, 15, 30),
    "pressure": ("Тиск", "кПа", 97, 104, 90, 110),          # земний тиск 101,3 кПа
    "oxygen": ("Кисень", "%", 19.5, 23.5, 18, 25),            # 21 % як на Землі; <19,5 % — нестача
    "co2": ("CO₂", "ppm", None, 3950, None, 7000),            # 3 і 5,3 мм рт.ст. при тиску 101,3 кПа
    "radiation": ("Радіація", "мкЗв/год", None, 85, None, 420),  # 2 і 10 мЗв за добу
}


def evaluate_cabin(readings):
    items = []
    for key, (name, unit, *_rest) in CABIN.items():
        if readings.get(key) is not None:
            level, side = classify(key, readings[key], CABIN)
            items.append({"key": key, "name": name, "unit": unit, "value": readings[key],
                          "level": level, "side": side, "label": LEVELS[level]})
    return items


CABIN_ACTIONS = {  # ключ: (дія при "увага", дія при "критично")
    "temp": ("Відрегулюйте терморегуляцію модуля.", "Перевірте терморегуляцію, перейдіть у модуль із комфортною температурою, повідомте ЦУП."),
    "pressure": ("Перевірте герметичність люків і клапанів.", "Шукайте розгерметизацію, надіньте скафандри, повідомте ЦУП."),
    "oxygen": ("Перевірте генератор кисню та вентиляцію.", "Увімкніть резервний кисень, перейдіть у безпечний модуль, повідомте ЦУП."),
    "co2": ("Перевірте видалення CO₂, зменште фізичне навантаження.", "Увімкніть резервний скрубер, перейдіть у безпечний модуль, повідомте ЦУП."),
    "radiation": ("Перевірте дозиметри, зменште час поза укриттям.", "Негайно в радіаційне укриття, повідомте ЦУП."),
}


def cabin_actions(items):
    acts = [{"level": i["level"], "metric": "Кабіна: " + i["name"], "text": CABIN_ACTIONS[i["key"]][i["level"] - 1]}
            for i in items if i["level"]]
    return sorted(acts, key=lambda a: -a["level"])


def validate(values):
    """Перевіряє ручне введення → {ключ: число}. Кидає ValueError зі зрозумілим текстом."""
    import math
    if not isinstance(values, dict):
        raise ValueError("Поле values має бути об'єктом {показник: значення}")
    out = {}
    for key, raw in values.items():
        if raw is None or raw == "":
            continue
        if key not in METRICS:
            raise ValueError(f"Невідомий показник: {key}")
        name, unit = METRICS[key][:2]
        try:
            if isinstance(raw, bool):
                raise ValueError
            value = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            raise ValueError(f"{name}: введіть число") from None
        lo, hi = LIMITS[key]
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{name}: значення має бути від {lo} до {hi} {unit}")
        out[key] = round(value, 1)
    if not out:
        raise ValueError("Введіть хоча б один показник")
    return out


def health_score(items, trends=()):
    """Індекс здоров'я 0–100: мінус 12 за кожен показник «увага», мінус 30 за «критично», мінус 5 за тривожну тенденцію."""
    score = 100 - sum({1: 12, 2: 30}.get(i["level"], 0) for i in items) - 5 * len(trends)
    return max(0, min(100, score))
