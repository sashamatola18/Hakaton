"""Переговори екіпажу: репліки, якими астронавти реагують на стан одне одного.

Функції повертають список (хто говорить, текст, рівень). Тексти написані так, щоб їх
було зручно озвучувати синтезатором мовлення (без скорочень і спецсимволів).
"""
import random


def num(v):
    return f"{v:g}".replace(".", ",")


SPOKEN = {  # як показник звучить у репліці
    "heart_rate": lambda v: f"пульс {v:.0f}",
    "spo2": lambda v: f"сатурація {v:.0f} відсотків",
    "systolic": lambda v: f"тиск {v:.0f}",
    "diastolic": lambda v: f"нижній тиск {v:.0f}",
    "glucose": lambda v: f"глюкоза {num(v)}",
    "temperature": lambda v: f"температура {num(v)}",
    "resp_rate": lambda v: f"дихання {v:.0f} на хвилину",
    "co2": lambda v: f"вуглекислий газ {num(v)}",
    "radiation": lambda v: f"доза радіації {num(v)} мілізіверта",
    "sleep": lambda v: f"сон лише {num(v)} години",
}
FEEL = {  # (показник, сторона): як це відчуває астронавт
    ("heart_rate", "high"): "Серце калатає",
    ("heart_rate", "low"): "Відчуваю слабкість, пульс рідкий",
    ("spo2", "low"): "Важко дихати, паморочиться в голові",
    ("systolic", "low"): "Темніє в очах, сильна слабкість",
    ("systolic", "high"): "Болить голова, тисне у скронях",
    ("diastolic", "low"): "Паморочиться в голові, слабкість",
    ("diastolic", "high"): "Болить голова",
    ("glucose", "low"): "Тремтять руки, кидає в піт, дуже хочеться їсти",
    ("glucose", "high"): "Сильна спрага і втома",
    ("temperature", "high"): "Мене лихоманить",
    ("temperature", "low"): "Дуже мерзну",
    ("resp_rate", "high"): "Дихаю часто, не вистачає повітря",
    ("resp_rate", "low"): "Дихання сповільнене",
    ("co2", "high"): "Болить голова, у відсіку душно",
    ("radiation", "high"): "Мій дозиметр показує підвищену дозу",
    ("sleep", "low"): "Я майже не спав, важко зосередитись",
}
CABIN_SPOKEN = {"temp": "температура", "pressure": "тиск", "oxygen": "кисень",
                "co2": "вуглекислий газ", "radiation": "радіація"}


def _bad(result):
    return sorted((i for i in result["items"] if i["level"]), key=lambda i: -i["level"])


def _said(items):
    return ", ".join(SPOKEN[i["key"]](i["value"]) for i in items[:2])


def _lead(name, crew):
    """Хто веде розмову: командир, а якщо погано саме командирові — пілот."""
    return crew[1] if name == crew[0] else crew[0]


def status_lines(name, prev, result, crew, voc, blood="", allergies=""):
    """Репліки при зміні стану астронавта (prev → result['overall'])."""
    level, lead = result["overall"], _lead(name, crew)
    bad = _bad(result)
    if level == 0:
        return [(name, "Показники знову в нормі, почуваюся добре.", 0),
                (lead, f"Чудово, {voc[name]}. Повертайся до роботи поступово.", 0)]
    feel = FEEL.get((bad[0]["key"], bad[0]["side"]), "Почуваюся недобре") if bad else "Почуваюся недобре"
    advice = next((a["text"] for a in result["actions"] if a["level"]), "")
    if level == 2:
        helper = random.choice([c for c in crew if c not in (name, lead)] or [lead])
        known = [x for x in (f"група крові {blood}" if blood and blood != "не вказано" else "",
                             f"алергія: {allergies}" if allergies not in ("", "немає", "не вказано") else "без алергій") if x]
        medical = f" З медичної картки: {', '.join(known)}." if blood or allergies else ""
        return [(lead, f"{voc[name].capitalize()}, бачу червоні показники: {_said(bad)}. Як почуваєшся?", 2),
                (name, f"{feel}. Припиняю роботу.", 2),
                (helper, "Іду на допомогу з аптечкою. Викликаю лікаря польоту." + medical, 2),
                (lead, f"Діємо за протоколом. {advice}", 2)]
    if prev == 2:
        return [(name, f"Мені трохи краще, але ще не норма: {_said(bad)}.", 1),
                (lead, "Прийняв. Продовжуй відпочивати, стежимо за показниками.", 1)]
    return [(name, f"Екіпаже, у мене {_said(bad)}. {feel}.", 1),
            (lead, f"Прийняв, {voc[name]}. {advice}", 1)]


def cabin_lines(item, advice, crew):
    """Репліки, коли параметр кабіни вийшов за норму або повернувся."""
    what = CABIN_SPOKEN.get(item["key"], item["name"])
    value = f"{num(item['value'])} {item['unit']}".replace("ppm", "пі-пі-ем").replace("мкЗв/год", "мікрозіверта на годину") \
        .replace("кПа", "кілопаскалів").replace("°C", "градуса").replace("%", "відсотка")
    if item["level"] == 0:
        return [(crew[1], f"Кабіна: {what} знову в нормі.", 0), (crew[0], "Прийняв. Продовжуємо за планом.", 0)]
    word = "Увага" if item["level"] == 1 else "Тривога"
    return [(crew[1], f"{word}, кабіна: {what} {value}.", item["level"]),
            (crew[0], f"Прийняв. {advice}", item["level"])]


def routine_lines(latest, cabin, mission, crew, voc):
    """Спокійна розмова, коли все в нормі: перекличка, доповідь про політ, нагадування."""
    a, b = random.sample(crew, 2)
    vals = {i["key"]: i["value"] for i in latest[b]["items"]} if b in latest else {}
    options = [
        [(a, f"{voc[b].capitalize()}, як самопочуття?", 0),
         (b, f"Усе гаразд: пульс {vals.get('heart_rate', 70):.0f}, температура {num(vals.get('temperature', 36.6))}.", 0)],
        [(crew[1], f"До Землі {mission['distance_km'] // 1000} тисяч кілометрів, місію виконано на "
                   f"{mission['percent']:.0f} відсотків.", 0),
         (crew[0], "Прийняв. Усі системи в нормі, працюємо за планом.", 0)],
        [(a, "Нагадую екіпажу: за розкладом вода і тренування.", 0), (b, "Прийняв, дякую.", 0)],
        [(a, f"{voc[b].capitalize()}, перевір, будь ласка, датчики кабіни.", 0),
         (b, f"Перевірив: температура {num(cabin.get('temp', 22))} градуса, кисень {num(cabin.get('oxygen', 21))} "
             f"відсотка. Усе в нормі.", 0)],
    ]
    return random.choice(options)


def doctor_lines(name, crew, voc):
    lead = _lead(name, crew)
    return [(lead, f"Центр керування, потрібна консультація лікаря польоту для члена екіпажу. {voc[name].capitalize()}, "
                   f"залишайся на зв'язку.", 1),
            (name, "Прийняв, чекаю на лікаря.", 1)]


def reply_lines(name, crew):
    """Коротка відповідь на репліку, яку ввів користувач від імені астронавта."""
    other = random.choice([c for c in crew if c != name])
    return [(other, random.choice(["Прийняв.", "Зрозумів, дякую.", "Чую тебе добре. Прийняв."]), 0)]
