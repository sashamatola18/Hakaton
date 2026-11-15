"""Бортовий ШІ-асистент «Астра»: відповідає на запитання в переговорах екіпажу.

Як міркує асистент:
1. Розбирає запитання: про кого воно (прізвище в будь-якому відмінку, «командир», «пілот»),
   про який показник і який у нього намір (стан, чому, що робити, порівняння, норма тощо).
2. Якщо запитання неповне («а в Янка?», «а тиск?»), бере відсутнє з попереднього запитання.
3. Спершу відповідає прямо на запитане («Так»/«Ні», число, ім'я), потім додає головне:
   що поза нормою, причину, рекомендацію, алергії.
4. Ніколи не каже «все добре», якщо хоч один показник екіпажу чи кабіни поза нормою.

Працює без інтернету; усі відповіді складаються зі справжніх поточних даних панелі.
"""
import re

from .assessment import METRICS, SOURCES
from .dialogue import SPOKEN, num

NAME = "ШІ «Астра»"
OPERATOR = "Оператор"
STATE = ["у нормі", "потребує уваги", "критичний"]

# показник: (слова, за якими його впізнаємо; назва у відповіді; назва в родовому відмінку)
METRIC_WORDS = {
    "heart_rate": (("пульс", "серц", "серцебит"), "Пульс", "пульсу"),
    "spo2": (("сатурац", "spo", "кисень у крові", "кисень в крові", "кисню в крові", "кисню у крові"), "Сатурація", "сатурації"),
    "systolic": (("тиск", "давлен"), "Тиск", "верхнього тиску"),
    "temperature": (("температур", "гарячк", " жар"), "Температура", "температури"),
    "resp_rate": (("дихан", "дихає", "вдих"), "Дихання", "частоти дихання"),
    "glucose": (("глюкоз", "цукор", "цукр"), "Глюкоза", "глюкози"),
    "sleep": ((" сон ", " сну ", "спав", "спал", "висп"), "Сон", "сну"),
    "radiation": (("радіац", "опромін", " доза", " дозу"), "Доза радіації за добу", "дози радіації за добу"),
    "co2": (("вуглекисл", "co2", "со2"), "Вуглекислий газ", "вуглекислого газу"),
}
CABIN_UNITS = {"temp": "градуса", "pressure": "кілопаскаля", "oxygen": "відсотків",
               "co2": "пі-пі-ем", "radiation": "мікрозіверта на годину"}
CABIN_NAMES = {"temp": "температура", "pressure": "тиск", "oxygen": "кисень",
               "co2": "вуглекислий газ", "radiation": "радіація"}
HELP = ("Я бортовий асистент. Можу доповісти стан екіпажу або однієї людини, назвати будь-який показник і його норму, "
        "пояснити причину тривоги, порадити, що робити, сказати, хто може працювати, у кого найвищий пульс, "
        "хто підходить як донор, що в кабіні і де ми зараз.")

# намір: слова-ознаки. Порядок важливий: вище — конкретніші запитання.
INTENTS = [
    ("help", ("що ти вмієш", "що вмієш", "допомога", " команди ", "що можеш", "хто ти", "що ти можеш")),
    ("thanks", ("дякую", "спасибі", " дяка ")),
    ("donor", ("донор", "перелив", "сумісн", "підійде кров", "підходить кров", "дати кров", "здати кров")),
    ("blood", ("група крові", "групу крові", "групи крові", "яка кров")),
    ("allergy", ("алерг",)),
    ("callsign", ("позивн",)),
    ("index", ("індекс", "готовн", " бал ", " бали ", "оцінк", "рейтинг")),
    ("norm", (" норма ", " норму ", " норми ", "нормальн", " межі ", " межа ", "поріг", "пороги")),
    ("monthly", ("за місяць", "середн", "місячн")),
    ("extreme", ("найвищ", "найбільш", "максимальн", "найнижч", "найменш", "мінімальн", "найгірш", "найкращ", "найчастіш")),
    ("why", ("чому", "через що", "причин", "від чого", "що сталося", "що трапилось", "що трапилося")),
    ("canwork", ("може працювати", "можна працювати", "може продовж", "придатн", "допущен", "до роботи", "працездатн")),
    ("advice", ("що робити", "порад", "рекоменд", "як допомогти", "допомож", "як діяти", "чим допомогти", "як лікувати")),
    ("alerts", ("кому погано", "хто хвор", "тривог", "проблем", "небезпе", "червон", "критичн", "кому зле", "відхилен")),
    ("time", ("котра година", "котра зараз", "скільки часу минуло", "час місії", "який час", "скільки летимо")),
    ("mission", ("відстан", "далеко", "де ми", "до землі", "від землі", "місія", "місії", "політ", "польот", "залишилось",
                 "залишилося", "повернемо", "повернення", "траєктор", " місяц", "коли додому")),
    ("status", ("стан", "статус", "доповід", "доповіс", "звіт", "показник", "здоров", "самопочут", "состояни")),
    ("how", ("як справи", "як ти", "як ви", "як діла", "як життя", "як воно", "почува", "все добре", "усе добре",
             "все гаразд", "усе гаразд", "все в нормі", "усе в нормі", "как дела", "як ся ма", "що нового", "як там", "в порядку")),
    ("crew", ("хто в екіпаж", "склад екіпаж", "хто на борту", "скільки людей")),
    ("greet", ("привіт", "вітаю", "добрий день", "доброго", " хай ", "добрий вечір")),
]


def _has(text, *words):
    return any(w in text for w in words)


def plural(n, one, few, many):
    """1 година, 2 години, 5 годин."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def _stem(name):
    """«Стопчанський Н.» → «стопчанськ»: щоб упізнавати прізвище в будь-якому відмінку."""
    return re.sub(r"[аяоуюиіїей]+$", "", name.split()[0].lower())


def _short(name):
    return name.split()[0]


def _vals(result):
    return {i["key"]: i for i in result["items"]}


def _norm(key):
    """Норма показника словами: «від 95», «до 3», «50–100»."""
    _, _, lo, hi, _, _ = METRICS[key]
    return f"{num(lo)}–{num(hi)}" if lo is not None and hi is not None else f"від {num(lo)}" if lo is not None else f"до {num(hi)}"


def _value(key, v):
    """Значення показника для відповіді (тиск — «118 на 76»)."""
    if key not in v:
        return "немає даних"
    if key == "systolic" and "diastolic" in v:
        return f"{v['systolic']['value']:.0f} на {v['diastolic']['value']:.0f}"
    return SPOKEN[key](v[key]["value"]).split(" ", 1)[-1]


def _vitals(v):
    return (f"пульс {_value('heart_rate', v)}, тиск {_value('systolic', v)}, "
            f"температура {_value('temperature', v)}, сатурація {_value('spo2', v)}")


def _bad(result):
    return sorted((i for i in result["items"] if i["level"]), key=lambda i: -i["level"])


def _deviations(result, limit=3):
    return ", ".join(f"{SPOKEN[i['key']](i['value'])} при нормі {_norm(i['key'])}" for i in _bad(result)[:limit])


def _cause(result, ctx):
    key = result.get("incident") or result.get("scenario")
    return ctx["scenarios"].get(key, "") if key else ""


def _allergy_note(name, ctx):
    a = ctx["profiles"].get(name, {}).get("allergies", "немає")
    return "" if a in ("немає", "не вказано", "") else f" Врахуйте алергію: {a}."


def person_report(name, ctx, brief=False):
    r = ctx["latest"].get(name)
    if not r:
        return f"{_short(name)}: даних немає."
    bad = _bad(r)
    if not bad:
        if brief:
            return f"{_short(name)} — норма."
        trend = "".join(f" Зверніть увагу: {t['metric'].lower()} {t['text']}" for t in r.get("trends", [])[:1])
        return f"{_short(name)}: стан у нормі — {_vitals(_vals(r))}.{trend}"
    if brief:
        return f"{_short(name)} — стан {STATE[r['overall']]}: " + ", ".join(SPOKEN[i["key"]](i["value"]) for i in bad[:3]) + "."
    cause = _cause(r, ctx)
    advice = next((a["text"] for a in r["actions"] if a["level"] and a["metric"] != "Алергія"), "")
    return (f"{_short(name)}: стан {STATE[r['overall']]}. Поза нормою: {_deviations(r)}."
            + (f" Імовірна причина: {cause.lower()}." if cause else "")
            + f" Рекомендація: {advice}" + _allergy_note(name, ctx))


def cabin_report(ctx):
    items = ctx["cabin"]
    bad = [i for i in items if i["level"]]
    if not bad:
        return "Кабіна в нормі: " + ", ".join(f"{CABIN_NAMES[i['key']]} {num(i['value'])} {CABIN_UNITS[i['key']]}" for i in items) + "."
    return ("У кабіні відхилення: " + ", ".join(f"{CABIN_NAMES[i['key']]} {num(i['value'])} {CABIN_UNITS[i['key']]}" for i in bad)
            + ". Решта параметрів у нормі. " + " ".join(a["text"] for a in ctx["cabin_actions"][:1]))


def _all_good(ctx):
    return all(r["overall"] == 0 for r in ctx["latest"].values()) and not any(i["level"] for i in ctx["cabin"])


def _ill(ctx):
    """Хто поза нормою: спершу критичні."""
    return sorted((n for n in ctx["crew"] if ctx["latest"].get(n, {}).get("overall")),
                  key=lambda n: -ctx["latest"][n]["overall"])


def _troubles(ctx):
    parts = [person_report(n, ctx, brief=True) for n in _ill(ctx)]
    if any(i["level"] for i in ctx["cabin"]):
        parts.append(cabin_report(ctx))
    return " ".join(parts)


def crew_report(ctx):
    ill = _ill(ctx)
    healthy = [_short(n) for n in ctx["crew"] if n not in ill]
    cabin = "Кабіна в нормі." if not any(i["level"] for i in ctx["cabin"]) else cabin_report(ctx)
    if not ill:
        return f"Доповідаю: екіпаж здоровий, усі четверо в нормі — {', '.join(healthy)}. {cabin}" if len(healthy) == 4 \
            else f"Доповідаю: екіпаж здоровий, усі в нормі — {', '.join(healthy)}. {cabin}"
    first = " ".join(person_report(n, ctx, brief=True) for n in ill)   # найважливіше — першим
    rest = f" У нормі: {', '.join(healthy)}." if healthy else ""
    return f"Доповідаю. {first}{rest} {cabin}"


def mission_report(ctx):
    m = ctx["mission"]
    h, mi = m["remaining_s"] // 3600, m["remaining_s"] % 3600 // 60
    return (f"Ми за {plural(m['distance_km'] // 1000, 'тисячу', 'тисячі', 'тисяч')} кілометрів від Землі. "
            f"Місію виконано на {plural(round(m['percent']), 'відсоток', 'відсотки', 'відсотків')}, "
            f"до повернення {plural(h, 'година', 'години', 'годин')} {plural(mi, 'хвилина', 'хвилини', 'хвилин')}.")


def readiness(ctx):
    """Готовність екіпажу: середній індекс здоров'я, %."""
    scores = [r.get("score", 100) for r in ctx["latest"].values()]
    return round(sum(scores) / len(scores)) if scores else 0


def report(ctx, events=()):
    """Медичний звіт: розділи з рядками тексту, зібрані з поточних даних."""
    m = ctx["mission"]
    e = m.get("elapsed_s", 0)
    ill = _ill(ctx)
    summary = [f"Час місії: {plural(e // 3600, 'година', 'години', 'годин')} {plural(e % 3600 // 60, 'хвилина', 'хвилини', 'хвилин')} від старту.",
               mission_report(ctx),
               f"Готовність екіпажу: {readiness(ctx)} зі 100.",
               "Висновок: екіпаж здоровий, обмежень немає." if _all_good(ctx) else
               "Висновок: є відхилення, потрібна увага. " + _troubles(ctx)]
    sections = [{"title": "Загальний висновок", "lines": summary}]
    for n in ill + [x for x in ctx["crew"] if x not in ill]:   # спершу ті, кому погано
        r = ctx["latest"].get(n)
        if not r:
            continue
        prof = ctx["profiles"].get(n, {})
        lines = [person_report(n, ctx),
                 f"Індекс здоров'я: {r.get('score', 100)} зі 100.",
                 "Усі показники: " + ", ".join(f"{i['name']} {num(i['value'])} {i['unit']}" for i in r["items"]) + ".",
                 f"Медична картка: група крові {prof.get('blood', 'не вказано')}, алергії: {prof.get('allergies', 'не вказано')}."]
        rows = [x for x in ctx["monthly"](n) if not x["demo"]]
        if rows:
            lines.append(f"Цього місяця: вимірів {rows[0]['readings']}, з них «увага» {rows[0]['warn']}, «критично» {rows[0]['crit']}.")
        sections.append({"title": f"{n}, {r.get('role', '').lower()}", "lines": lines})
    sections.append({"title": "Кабіна", "lines": [cabin_report(ctx)]})
    if events:
        sections.append({"title": "Останні події", "lines": list(events)})
    return sections


def parse_blood(text):
    """«II (A) Rh+» → ("A", "+"); нерозбірливий запис → None."""
    m = re.search(r"\(\s*([AB0OАВО]{1,2})\s*\)\s*Rh\s*([+\-−])", text or "", re.I)
    if not m:
        return None
    abo = m.group(1).upper().translate(str.maketrans("АВО0", "ABOO"))
    return abo, "+" if m.group(2) == "+" else "-"


def can_donate(donor, recipient):
    """Сумісність еритроцитів: антигени донора мають бути і в реципієнта; Rh− підходить усім."""
    d, r = parse_blood(donor), parse_blood(recipient)
    if not d or not r:
        return False
    antigens = lambda abo: set(abo) - {"O"}
    return antigens(d[0]) <= antigens(r[0]) and (d[1] == "-" or r[1] == "+")


def _find_people(text, ctx):
    found = [n for n in ctx["crew"] if _stem(n) in text]
    if _has(text, "командир", "капітан"):
        found.append(ctx["crew"][0])
    if _has(text, "пілот"):
        found.append(ctx["crew"][1])
    return list(dict.fromkeys(found))


def _find_metric(text, cabin_q):
    for key, (words, _, _) in METRIC_WORDS.items():
        if _has(text, *words) and not (cabin_q and key in ("systolic", "temperature", "co2", "radiation")):
            return key
    return None


def answer(text, ctx):
    """Повертає відповідь асистента на запитання `text`.

    ctx: crew (список імен), latest (ім'я → оцінка), cabin (показники кабіни), cabin_actions, mission,
    selected (обраний на панелі), scenarios (назви), profiles (ім'я → анкета), monthly (функція),
    memory (словник, у якому асистент пам'ятає попереднє запитання).
    """
    t = " " + re.sub(r"[^\w\s₂]", " ", text.lower().replace("ʼ", "").replace("'", "").replace("’", "")) + " "
    t = re.sub(r"\s+", " ", t)
    mem = ctx.setdefault("memory", {})
    people = _find_people(t, ctx)
    everyone = _has(t, " всі ", " всіх ", " усі ", " усіх ", "екіпаж", "кожн")
    cabin_q = _has(t, "кабін", "повітр", "атмосфер", "відсік", "на борту") or (_has(t, "кисень", "кисню") and not _has(t, "крові"))
    metric = _find_metric(t, cabin_q)
    intent = next((name for name, words in INTENTS if _has(t, *words)), None)
    if intent == "how" and metric:       # «як тиск», «як там пульс» — це про показник
        intent = None
    if intent == "status" and metric and "показник" not in t:
        intent = None                    # «який стан тиску» теж про показник
    asks_yes_no = t.startswith(" чи ") or " чи " in t
    follow_up = t.startswith(" а ") or t.startswith(" і ") or len(t.split()) <= 3

    # неповне запитання: бракує наміру або людини — беремо з попереднього
    if intent is None and not metric and not cabin_q and people and mem.get("intent"):
        intent, metric = mem["intent"], mem.get("metric")
    if metric and not people and not everyone and follow_up and mem.get("people") and intent in (None, "norm"):
        people = mem["people"] if intent is None else people
    if intent is None:
        intent = "metric" if metric else "cabin" if cabin_q else None
    if intent in ("status", "how", "alerts", "why", "advice") and cabin_q and not people:
        intent = "cabin_why" if intent == "why" else "cabin"
    mem.update(intent=intent or mem.get("intent"), people=people or ([] if everyone else mem.get("people", [])),
               metric=metric or (mem.get("metric") if intent == "metric" else None))

    latest, crew = ctx["latest"], ctx["crew"]
    if intent == "help":
        return HELP
    if intent == "thanks":
        return "Завжди на зв'язку."
    if intent == "donor":
        if not people:
            return "Назвіть, кому потрібна кров, наприклад: хто може бути донором для Янка."
        rec = people[0]
        blood = ctx["profiles"][rec]["blood"]
        if not parse_blood(blood):
            return f"Група крові {_short(rec)} у картці не вказана, тому сумісність визначити не можу."
        donors = [n for n in crew if n != rec and can_donate(ctx["profiles"][n]["blood"], blood)]
        fit = [n for n in donors if latest.get(n, {}).get("overall", 0) == 0]
        if not donors:
            return f"{_short(rec)} має групу {blood}. Серед екіпажу сумісних донорів немає. Потрібна консультація лікаря польоту."
        text_d = ", ".join(f"{_short(n)} ({ctx['profiles'][n]['blood']})" for n in donors)
        note = "" if len(fit) == len(donors) else " Зараз здорові з них: " + (", ".join(_short(n) for n in fit) or "ніхто") + "."
        return f"{_short(rec)} має групу {blood}. Сумісні донори в екіпажі: {text_d}.{note} Остаточне рішення — за лікарем польоту."
    if intent == "index":
        who = people or crew
        parts = ", ".join(f"{_short(n)} {latest[n].get('score', 100)}" for n in who if n in latest)
        return f"Індекс здоров'я зі ста: {parts}. Готовність екіпажу {plural(readiness(ctx), 'відсоток', 'відсотки', 'відсотків')}."
    if intent == "blood":
        return "Група крові. " + " ".join(f"{_short(n)}: {ctx['profiles'][n]['blood']}." for n in (people or crew))
    if intent == "allergy":
        who = people or crew
        if not people and all(ctx["profiles"][n]["allergies"] == "немає" for n in who):
            return "Алергій в екіпажі немає."
        return "Алергії. " + " ".join(f"{_short(n)}: {ctx['profiles'][n]['allergies']}." for n in who)
    if intent == "callsign":
        return " ".join(f"{_short(n)} — позивний {ctx['profiles'][n]['callsign']}." for n in (people or crew))
    if intent == "norm":
        if not metric:
            return "Назвіть показник, наприклад: яка норма пульсу. Усі норми є в таблиці внизу панелі."
        _, unit, _, _, cl, ch = METRICS[metric]
        crit = " або ".join(x for x in (f"нижче {num(cl)}" if cl is not None else "", f"вище {num(ch)}" if ch is not None else "") if x)
        extra = " Нижній тиск: норма 60–89." if metric == "systolic" else ""
        return f"Норма {METRIC_WORDS[metric][2]}: {_norm(metric)} {unit}. Критично: {crit}.{extra} {SOURCES[metric]}"
    if intent == "monthly":
        who = (people or ([ctx["selected"]] if ctx.get("selected") in crew else crew[:1]))[0]
        rows = [m for m in ctx["monthly"](who) if not m["demo"]]
        if not rows or "heart_rate" not in rows[0]["metrics"]:
            return f"{_short(who)}: місячних даних ще немає."
        m = rows[0]
        return (f"{_short(who)}, цей місяць: вимірів {m['readings']}, середній пульс {num(round(m['metrics']['heart_rate']['avg']))}, "
                f"середня температура {num(round(m['metrics']['temperature']['avg'], 1))}. Критичних вимірів: {m['crit']}.")
    if intent == "extreme":
        if not metric:
            ill = _ill(ctx)
            return "Усі почуваються однаково добре: показники в нормі." if not ill else f"Найгірший стан зараз: {person_report(ill[0], ctx, brief=True)}"
        low = _has(t, "найнижч", "найменш", "мінімальн") or (metric in ("sleep", "spo2") and _has(t, "найгірш"))
        rows = [(v[metric]["value"], n, v) for n in crew if (v := _vals(latest.get(n, {"items": []}))).get(metric)]
        if not rows:
            return "Даних для порівняння немає."
        val, who, v = (min if low else max)(rows, key=lambda r: r[0])
        mark = "у межах норми" if not v[metric]["level"] else "поза нормою"
        return (f"{'Найнижчий' if low else 'Найвищий'} показник — {METRIC_WORDS[metric][1].lower()} {_value(metric, v)}: "
                f"{_short(who)}. Це {mark} ({_norm(metric)}).")
    if intent == "cabin_why":
        bad = [i for i in ctx["cabin"] if i["level"]]
        return "У кабіні тривог немає, усі параметри в нормі." if not bad else cabin_report(ctx)
    if intent == "why":
        who = people or _ill(ctx)
        if not who:
            bad_cabin = [i for i in ctx["cabin"] if i["level"]]
            return cabin_report(ctx) if bad_cabin else "Тривог немає: усі показники екіпажу й кабіни в нормі."
        out = []
        for n in who[:2]:
            r = latest.get(n)
            if not r or not r["overall"]:
                out.append(f"{_short(n)} у нормі, причин для тривоги немає.")
                continue
            cause = _cause(r, ctx)
            out.append(f"{_short(n)}: тривога через те, що {_deviations(r)}."
                       + (f" Імовірна причина: {cause.lower()}." if cause else " Точну причину датчики не визначають — потрібен огляд."))
        return " ".join(out)
    if intent == "metric":
        who = people or crew
        title = METRIC_WORDS[metric][1]
        parts, off = [], []
        for n in who:
            r = latest.get(n)
            if r:
                v = _vals(r)
                parts.append(f"{_short(n)} {_value(metric, v)}")
                keys = ("systolic", "diastolic") if metric == "systolic" else (metric,)
                if any(v.get(k, {}).get("level") for k in keys):
                    off.append(_short(n))
        verdict = f"Усе в межах норми ({_norm(metric)})." if not off else f"Поза нормою ({_norm(metric)}): {', '.join(off)}."
        if len(parts) == 1:
            verdict = f"Це в межах норми ({_norm(metric)})." if not off else f"Це поза нормою ({_norm(metric)})."
        return f"{title}: " + ", ".join(parts) + f". {verdict}"
    if intent == "cabin":
        ok = not any(i["level"] for i in ctx["cabin"])
        return ("Так. " if asks_yes_no and ok else "Ні. " if asks_yes_no else "") + cabin_report(ctx)
    if intent == "time":
        e = ctx["mission"].get("elapsed_s", 0)
        return f"Час місії: {plural(e // 3600, 'година', 'години', 'годин')} {plural(e % 3600 // 60, 'хвилина', 'хвилини', 'хвилин')} від старту."
    if intent == "mission":
        return mission_report(ctx)
    if intent == "canwork":
        who = people or crew
        out = []
        for n in who:
            r = latest.get(n, {"overall": 0})
            if r["overall"] == 0:
                out.append(f"{_short(n)} — так, може працювати.")
            elif r["overall"] == 1:
                out.append(f"{_short(n)} — лише легка робота після відпочинку: {_deviations(r, 2)}.")
            else:
                out.append(f"{_short(n)} — ні, роботу треба припинити: {_deviations(r, 2)}.")
        return " ".join(out)
    if intent == "advice":
        who = people or _ill(ctx)
        if not who:
            return cabin_report(ctx) if any(i["level"] for i in ctx["cabin"]) else \
                "Усі здорові, особливих дій не потрібно. Продовжуйте за розкладом: вода, тренування, сон."
        return " ".join(person_report(n, ctx) for n in who[:2])
    if intent == "alerts":
        if _all_good(ctx):
            return ("Ні, проблем немає" if asks_yes_no else "Проблем немає") + ": усі показники екіпажу й кабіни в нормі."
        return ("Так, є відхилення. " if asks_yes_no else "Є відхилення. ") + _troubles(ctx)
    if intent == "status":
        return " ".join(person_report(n, ctx) for n in people) if people else crew_report(ctx)
    if intent == "how":
        if people:
            out = []
            for n in people:
                r = latest.get(n, {"overall": 0, "items": []})
                out.append(f"{_short(n)} почувається добре: {_vitals(_vals(r))}." if r["overall"] == 0 else person_report(n, ctx))
            return ("Так. " if asks_yes_no and all(latest.get(n, {}).get("overall", 0) == 0 for n in people) else "") + " ".join(out)
        me = "У мене все штатно. " if _has(t, "як ти", " а ти ", "як ся ма", "у тебе") else ""
        if _all_good(ctx):
            return ("Так, все добре. " if asks_yes_no else me or "Все добре. ") + "Екіпаж здоровий, показники в нормі, системи кабіни працюють штатно."
        return ("Ні, не все добре. " if asks_yes_no else me + "Не все добре. " if me else "Не все добре. ") + _troubles(ctx)
    if intent == "crew":
        return f"На борту {len(crew)}: " + ", ".join(f"{_short(n)} — {latest[n]['role'].lower()}" for n in crew if n in latest) + "."
    if intent == "greet":
        return "Вітаю. Бортовий асистент на зв'язку. " + ("Усі показники в нормі." if _all_good(ctx) else "Є відхилення. " + _troubles(ctx))
    if people:   # назвали лише людину — найлогічніше доповісти її стан
        mem["intent"] = "status"
        return " ".join(person_report(n, ctx) for n in people)
    return "Не зрозуміла запитання. " + HELP
