"""HTTP-сервер: JSON API + веб-панель. Лише стандартна бібліотека Python."""
import argparse, collections, datetime, json, math, sys, threading, time, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .assessment import (LEVELS, LIMITS, METRICS, SOURCES, health_score, cabin_actions, detect_trends, evaluate,
                         evaluate_cabin, validate)
from . import VERSION, assistant, dialogue
from .assessment import CABIN_ACTIONS
from .profiles import profile_for
from .devices import CABIN_DEVICES, DEVICES, cabin_device, device_for
from .simulator import BASE, CABIN_SCENARIOS, NOISE, SCENARIO_NAMES, CabinSimulator, Simulator
from .storage import Storage

STATIC = Path(__file__).parent.parent / "static"
CREW = {  # ім'я: (роль, дата народження). Дати умовні — впишіть справжні.
    "Матола О.": ("Командир", "2004-03-14"),
    "Попялковська Л.": ("Пілот", "2005-07-02"),
    "Стопчанський Н.": ("Фахівець місії", "2004-11-21"),
    "Янко А.": ("Фахівець місії", "2005-05-09"),
}
VOCATIVE = {  # як до астронавта звертаються в переговорах
    "Матола О.": "командире", "Попялковська Л.": "Попялковська", "Стопчанський Н.": "Стопчанський", "Янко А.": "Янко",
}
FEMALE = {"Попялковська Л."}  # для жіночих форм у репліках і жіночого голосу
FEMININE = (("Прийняв", "Прийняла"), ("Зрозумів", "Зрозуміла"), ("Перевірив", "Перевірила"), ("не спав", "не спала"))
INTERVAL = 2  # секунд між вимірами симуляції
TALK_COOLDOWN = 8   # секунд: один астронавт не коментує свій стан частіше
TALK_IDLE = 40      # секунд тиші, після яких екіпаж починає спокійну розмову
talk = {"last": 0.0, "by": {}}
ai_memory = {}  # бортовий ШІ пам'ятає попереднє запитання, щоб розуміти уточнення


def say(lines):
    if lines:
        fixed = []
        for who, text, level in lines:
            if who in FEMALE:  # «Прийняв» → «Прийняла» тощо
                for m, f in FEMININE:
                    text = text.replace(m, f)
            fixed.append((who, text, level))
        lines = fixed
        store.say(lines)
        talk["last"] = time.time()
PHOTO_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
state = {"paused": False, "sim": True, "incidents": True}
lock = threading.RLock()  # захищає спільний стан від одночасних запитів і потоку симуляції


def calc_age(dob):
    d, t = datetime.date.fromisoformat(dob), datetime.date.today()
    return t.year - d.year - ((t.month, t.day) < (d.month, d.day))


sims = {name: Simulator() for name in CREW}
store = Storage()
latest, last_data, manual_keys = {}, {}, {}
cabin = CabinSimulator()
cabin_hist = collections.deque(maxlen=60)
cabin_levels = {}
# Параметри польоту взято з реального обльоту Місяця «Артеміда-2» (квітень 2026 року):
# тривалість 9 діб 1 год 32 хв, найбільша відстань від Землі 406 771 км.
MISSION_S, MAX_DISTANCE_KM = 9 * 86400 + 3600 + 32 * 60, 406_771
START, ELAPSED0 = time.time(), 155 * 3600  # демонстрація починається на 155-й годині польоту (~71 %)


def record_cabin():
    with lock:
        reading = {"ts": time.time(), **cabin.read()}
        cabin_hist.append(reading)
        for i in evaluate_cabin(reading):
            if cabin_levels.get(i["key"], 0) != i["level"]:
                store.log_event("Кабіна", i["level"],
                                f"Кабіна: {i['name']} — {LEVELS[i['level']]} ({i['value']} {i['unit']})")
                advice = CABIN_ACTIONS[i["key"]][i["level"] - 1] if i["level"] else ""
                say(dialogue.cabin_lines(i, advice, list(CREW)))
            cabin_levels[i["key"]] = i["level"]


def mission():
    elapsed = ELAPSED0 + time.time() - START
    p = min(elapsed / MISSION_S, 1)
    done = int(min(elapsed, MISSION_S))
    return {"remaining_s": MISSION_S - done, "elapsed_s": done,
            "duration_s": MISSION_S, "percent": round(p * 100, 1),
            "distance_km": int(MAX_DISTANCE_KM * math.sin(math.pi * p))}


def record(name, data, manual=False):
    """Оцінює показники, запам'ятовує та зберігає в історію.

    Ручний вимір може містити лише частину показників — решта береться з останнього виміру,
    щоб картка астронавта не втрачала дані.
    """
    with lock:
        if manual:
            manual_keys[name] = set(data)
            data = {**last_data.get(name, {}), **data}
        else:
            manual_keys.pop(name, None)
        result = evaluate(data)
        idx = list(CREW).index(name)
        profile = profile_for(idx)
        if result["overall"] and profile["allergies"] not in ("немає", "не вказано", ""):
            # алергія важлива саме тоді, коли людині можуть давати ліки
            result["actions"].append({"level": 1, "metric": "Алергія",
                                      "text": f"Перед будь-якими ліками врахуйте алергію: {profile['allergies']}."})
        prev = latest.get(name)
        if prev and prev["overall"] != result["overall"]:
            causes = ", ".join(i["name"] for i in result["items"] if i["level"]) or "усі показники в нормі"
            store.log_event(name, result["overall"], f"{name}: {LEVELS[result['overall']]} ({causes})")
            now = time.time()  # критичний стан озвучуємо завжди, решту — не частіше ніж раз на TALK_COOLDOWN
            if result["overall"] == 2 or now - talk["by"].get(name, 0) >= TALK_COOLDOWN:
                talk["by"][name] = now
                say(dialogue.status_lines(name, prev["overall"], result, list(CREW), VOCATIVE,
                                          blood=profile["blood"], allergies=profile["allergies"]))
        store.add(name, data, result["overall"])
        last_data[name] = data
        result["trends"] = detect_trends([h["data"] for h in store.history(name, 10)])
        result["score"] = health_score(result["items"], result["trends"])
        role, dob = CREW[name]
        live = sims[name].live_sources()
        for i in result["items"]:  # який пристрій дав значення (або що його ввели вручну)
            i["device"] = device_for(i["key"], idx)
            i["live"] = i["key"] in live
            if i["live"]:          # справжній датчик: показуємо його назву
                i["device"] = {**i["device"], "name": live[i["key"]], "serial": "Bluetooth"}
            i["manual"] = i["key"] in manual_keys.get(name, ()) and not i["live"]
        result.update(astronaut=name, ts=time.time(), role=role, dob=dob, age=calc_age(dob),
                      scenario=sims[name].scenario, incident=sims[name].incident,
                      profile=profile)
        latest[name] = result
        return result


def sync_cabin():
    """Кабіна спільна: сценарій кабіни діє, доки він увімкнений хоча б в одного астронавта."""
    active = [s.scenario for s in sims.values() if s.scenario in CABIN_SCENARIOS]
    cabin.inject(active[-1] if active else "reset")
    record_cabin()


def control(act):
    notes = {"pause": "Симуляцію призупинено", "resume": "Симуляцію відновлено", "reset": "Усі сценарії скинуто",
             "incidents_on": "Випадкові погіршення стану увімкнено", "incidents_off": "Випадкові погіршення стану вимкнено"}
    if act not in notes:
        raise ValueError("Невідома дія: очікується " + ", ".join(notes))
    with lock:
        if act == "reset":
            for s in sims.values():
                s.inject("reset")
            for n, s in sims.items():
                record(n, s.read())
            sync_cabin()
        elif act.startswith("incidents"):
            state["incidents"] = act == "incidents_on"
            if not state["incidents"]:  # поточні випадкові епізоди завершуємо одразу
                for n, s in sims.items():
                    if s.incident:
                        s.incident = None
                        record(n, s.read())
        elif state["paused"] == (act == "pause"):
            return state  # уже в потрібному стані — не засмічуємо журнал
        else:
            state["paused"] = act == "pause"
        store.log_event("Система", 0, notes[act])
    return state


def poll(interval):
    while True:
        try:
            if not state["paused"]:
                for name, sim in sims.items():
                    if state["incidents"]:
                        sim.maybe_incident()
                        started = sim.pop_started()
                        if started:
                            store.log_event(name, 1, f"{name}: раптове погіршення стану — {SCENARIO_NAMES[started]}")
                    record(name, sim.read())
                record_cabin()
                with lock:  # спокійна розмова, коли всі здорові й давно ніхто не говорив
                    calm = all(c["overall"] == 0 for c in latest.values()) and not any(cabin_levels.values())
                    if calm and time.time() - talk["last"] >= TALK_IDLE:
                        say(dialogue.routine_lines(latest, cabin_hist[-1], mission(), list(CREW), VOCATIVE))
        except Exception as e:  # симуляція не має зупинятися через одну помилку
            print("Помилка симуляції:", e, file=sys.stderr)
        time.sleep(interval)


def to_csv(rows):
    keys = list(METRICS)
    lines = [",".join(["time", *keys, "status"])]
    for r in rows:
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
        lines.append(",".join([t, *(str(r["data"].get(k, "")) for k in keys), LEVELS[r["overall"]]]))
    return "\r\n".join(lines).encode("utf-8-sig")


def monthly_csv(rows):
    keys = list(METRICS)
    head = ["month", *(f"{k}_{x}" for k in keys for x in ("avg", "min", "max")), "readings", "warn", "crit", "demo"]
    lines = [",".join(head)]
    for r in rows:
        cells = [r["month"]]
        for k in keys:
            m = r["metrics"].get(k)
            cells += [str(m[x]) for x in ("avg", "min", "max")] if m else ["", "", ""]
        lines.append(",".join(cells + [str(r["readings"]), str(r["warn"]), str(r["crit"]), str(int(r["demo"]))]))
    return "\r\n".join(lines).encode("utf-8-sig")


def ai_context(selected):
    """Усе, що бортовий ШІ знає про поточний стан (викликати під lock)."""
    crew = list(CREW)
    items = evaluate_cabin(cabin_hist[-1])
    return {"crew": crew, "latest": dict(latest), "cabin": items, "cabin_actions": cabin_actions(items),
            "mission": mission(), "selected": selected, "scenarios": SCENARIO_NAMES,
            "profiles": {n: profile_for(i) for i, n in enumerate(crew)}, "monthly": store.monthly,
            "memory": ai_memory}


def find_photo(stem):
    """Шукає static/photos/<stem>.jpg|.jpeg|.png|.webp → (шлях, тип) або None."""
    for ext, ctype in PHOTO_TYPES.items():
        photo = STATIC / "photos" / (stem + ext)
        if stem and photo.is_file():
            return photo, ctype


def meta():
    return {"version": VERSION, "interval": INTERVAL, "crew": list(CREW), "female": [n in FEMALE for n in CREW],
            "assistant": assistant.NAME, "operator": assistant.OPERATOR,
            "scenarios": SCENARIO_NAMES,
            "devices": {k: {"name": n, "model": c, "place": pl} for k, (n, c, pl) in DEVICES.items()},
            "cabin_devices": {k: cabin_device(k) for k in CABIN_DEVICES},
            "photos": [bool(find_photo(str(i))) for i in range(len(CREW))], "logo": bool(find_photo("logo")),
            "metrics": {k: {"name": n, "unit": u, "warn": [wl, wh], "crit": [cl, ch], "limits": LIMITS[k],
                            "source": SOURCES[k]}
                        for k, (n, u, wl, wh, cl, ch) in METRICS.items()}}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", headers=()):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith(("text", "application/json")) else ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _astronaut(self, query):
        name = query.get("astronaut", [""])[0]
        if name not in CREW:
            raise ValueError("Невідомий астронавт")
        return name

    def do_GET(self):
        try:
            self._get()
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._send(500, {"error": f"Внутрішня помилка: {e}"})

    do_HEAD = do_GET

    def _get(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
        if url.path == "/api/meta":
            return self._send(200, meta())
        if url.path == "/api/crew":
            with lock:
                return self._send(200, list(latest.values()))
        if url.path == "/api/cabin":
            with lock:
                items = evaluate_cabin(cabin_hist[-1])
                for i in items:
                    i["device"] = cabin_device(i["key"])
                return self._send(200, {"items": items, "history": list(cabin_hist), "mission": mission(),
                                        "readiness": round(sum(c.get("score", 100) for c in latest.values()) / max(len(latest), 1)),
                                        "paused": state["paused"], "sim": state["sim"],
                                        "incidents": state["incidents"],
                                        "actions": cabin_actions(items)})
        if url.path == "/api/dialogue":
            return self._send(200, store.dialogue())
        if url.path == "/api/report":
            with lock:
                ctx = ai_context(None)
                events = [f"{time.strftime('%H:%M:%S', time.localtime(e['ts']))} — {e['text']}" for e in store.events(8)]
                return self._send(200, {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "readiness": assistant.readiness(ctx),
                                        "sections": assistant.report(ctx, events)})
        if url.path == "/api/events":
            return self._send(200, store.events())
        if url.path.startswith("/photos/"):
            found = find_photo(Path(url.path).stem)  # /photos/0 або /photos/0.jpg — розширення шукаємо самі
            if found:
                return self._send(200, found[0].read_bytes(), found[1])
            return self._send(404, {"error": "фото не знайдено"})
        if url.path == "/api/history":
            return self._send(200, store.history(self._astronaut(query)))
        if url.path == "/api/actions":
            return self._send(200, store.actions(self._astronaut(query)))
        if url.path == "/api/monthly":
            return self._send(200, store.monthly(self._astronaut(query)))
        if url.path == "/api/export-monthly":
            name = self._astronaut(query)
            fname = f"astrohealth-monthly-{list(CREW).index(name) + 1}.csv"
            return self._send(200, monthly_csv(store.monthly(name, 120)), "text/csv",
                              [("Content-Disposition", f'attachment; filename="{fname}"')])
        if url.path == "/api/export":
            name = self._astronaut(query)
            fname = f"astrohealth-{list(CREW).index(name) + 1}-{time.strftime('%Y%m%d-%H%M%S')}.csv"
            return self._send(200, to_csv(store.history(name, 100000)), "text/csv",
                              [("Content-Disposition", f'attachment; filename="{fname}"')])
        self._send(404, {"error": "не знайдено"})

    def do_POST(self):
        try:
            self._post()
        except (ValueError, TypeError) as e:  # JSONDecodeError — теж ValueError
            self._send(400, {"error": str(e) or "Некоректний запит"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._send(500, {"error": f"Внутрішня помилка: {e}"})

    def _post(self):
        path = urlparse(self.path).path
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 <= size <= 65536:
            raise ValueError("Завеликий запит")
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Тіло запиту має бути коректним JSON") from None
        if not isinstance(body, dict):
            raise ValueError("Тіло запиту має бути JSON-об'єктом")
        if path == "/api/control":
            return self._send(200, control(body.get("action")))
        if path not in ("/api/simulate", "/api/readings", "/api/actions", "/api/dialogue", "/api/live"):
            return self._send(404, {"error": "не знайдено"})
        name = body.get("astronaut")
        if not isinstance(name, str) or name not in sims:
            raise ValueError("Невідомий астронавт")
        if path == "/api/simulate":
            with lock:
                sims[name].inject(body.get("scenario"))
                sync_cabin()
                return self._send(200, record(name, sims[name].read()))
        if path == "/api/live":  # дані зі справжнього датчика (наприклад, Bluetooth-пульсометра)
            values = validate(body.get("values", {}))
            source = " ".join(str(body.get("source") or "Зовнішній датчик").split())[:60]
            with lock:
                first = not sims[name].live_sources()
                sims[name].set_live(values, source)
                if first:
                    store.log_event(name, 0, f"{name}: підключено датчик «{source}»")
                if state["paused"] or not state["sim"]:   # симуляція не йде — записуємо вимір одразу
                    return self._send(200, record(name, values, manual=True))
                return self._send(200, latest[name])
        if path == "/api/readings":
            values = validate(body.get("values", {}))
            with lock:
                result = record(name, values, manual=True)
                shown = ", ".join(f"{METRICS[k][0]} {v:g}" for k, v in values.items())
                store.log_event(name, 0, f"{name}: ручний вимір ({shown})")
            return self._send(200, result)
        text = " ".join(str(body.get("text", "")).split())[:300]
        if path == "/api/dialogue":  # запитання оператора → відповідь бортового ШІ
            if not text:
                raise ValueError("Порожнє запитання")
            with lock:
                ctx = ai_context(name)
                items = ctx["cabin"]
                reply = assistant.answer(text, ctx)
                level = max([c["overall"] for c in latest.values()] + [i["level"] for i in items]) if "норм" not in reply[:40] else 0
                store.say([(assistant.OPERATOR, text, 0), (assistant.NAME, reply, level)])
                talk["last"] = time.time()
            return self._send(200, store.dialogue())
        if not text:
            raise ValueError("Порожня дія")
        if text.startswith("Викликано лікаря"):
            say(dialogue.doctor_lines(name, list(CREW), VOCATIVE))
        store.log_action(name, text)
        return self._send(200, store.actions(name))

    def log_message(self, *args):
        pass


def make_server(port=8000, sim=True, interval=INTERVAL, incidents=True, demo=True):
    """Готує початкові дані й повертає сервер (використовується і в тестах)."""
    state["sim"], state["incidents"] = sim, incidents and sim
    for name, s in sims.items():
        if demo:
            store.seed_demo(name, BASE, NOISE)
        record(name, s.read())
    record_cabin()
    if sim:
        threading.Thread(target=poll, args=(interval,), daemon=True).start()
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def running_copy(port):
    """Якщо на порту вже працює AstroHealth — повертає його версію («?» для дуже старих), інакше None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=1.5) as r:
            return str(json.load(r).get("version", "?"))
    except urllib.error.HTTPError:
        return "?"
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="AstroHealth Monitor")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-sim", action="store_true", help="вимкнути симуляцію датчиків")
    parser.add_argument("--no-incidents", action="store_true", help="без випадкових погіршень стану")
    parser.add_argument("--no-demo", action="store_true", help="не заповнювати попередні місяці демо-даними")
    parser.add_argument("--no-browser", action="store_true", help="не відкривати сторінку в браузері")
    args = parser.parse_args()
    print(f"AstroHealth Monitor, версія {VERSION}")
    print(f"Папка програми: {STATIC.parent}")
    port, server = args.port, None
    for attempt in range(10):
        try:
            server = make_server(port, not args.no_sim, incidents=not args.no_incidents, demo=not args.no_demo) \
                if attempt == 0 else ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            old = running_copy(port)
            if old:
                print(f"УВАГА: на порту {port} уже працює інша копія AstroHealth (версія {old}).")
                print("       Саме її показує браузер за старою адресою. Закрийте її термінал або натисніть у ньому Ctrl+C.")
            else:
                print(f"Порт {port} зайнятий іншою програмою.")
            port += 1
            print(f"       Запускаю цю версію на порту {port}.")
    if server is None:
        sys.exit("Не вдалося знайти вільний порт. Закрийте інші копії програми й запустіть знову.")
    url = f"http://127.0.0.1:{port}"
    print(f"Відкрийте в браузері: {url}  (Ctrl+C — зупинити)")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nЗупинено.")
