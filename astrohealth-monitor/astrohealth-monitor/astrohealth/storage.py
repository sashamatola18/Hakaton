"""Зберігання історії вимірювань і місячних середніх у SQLite."""
import json, os, random, sqlite3, threading, time
from pathlib import Path


class Storage:
    def __init__(self, path=None):
        path = path or os.environ.get("ASTROHEALTH_DB") or Path(__file__).parent.parent / "astrohealth.db"
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("CREATE TABLE IF NOT EXISTS readings "
                        "(id INTEGER PRIMARY KEY, ts REAL, astronaut TEXT, data TEXT, overall INTEGER)")
        self.db.execute("CREATE TABLE IF NOT EXISTS actions "
                        "(id INTEGER PRIMARY KEY, ts REAL, astronaut TEXT, text TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events "
                        "(id INTEGER PRIMARY KEY, ts REAL, astronaut TEXT, level INTEGER, text TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS dialogue "
                        "(id INTEGER PRIMARY KEY, ts REAL, speaker TEXT, text TEXT, level INTEGER)")
        # Місячні підсумки. Оновлюються з кожним виміром, тому не залежать від очищення readings.
        self.db.execute("CREATE TABLE IF NOT EXISTS monthly_avg (astronaut TEXT, month TEXT, metric TEXT, "
                        "n INTEGER, total REAL, vmin REAL, vmax REAL, PRIMARY KEY (astronaut, month, metric))")
        self.db.execute("CREATE TABLE IF NOT EXISTS monthly_status (astronaut TEXT, month TEXT, readings INTEGER, "
                        "warn INTEGER, crit INTEGER, demo INTEGER DEFAULT 0, PRIMARY KEY (astronaut, month))")
        self.db.execute("DELETE FROM readings WHERE ts < ?", (time.time() - 7 * 86400,))  # тримаємо тиждень
        self.db.commit()

    def add(self, astronaut, data, overall, ts=None):
        ts = ts or time.time()
        month = time.strftime("%Y-%m", time.localtime(ts))
        with self.lock:
            self.db.execute("INSERT INTO readings(ts, astronaut, data, overall) VALUES (?,?,?,?)",
                            (ts, astronaut, json.dumps(data), overall))
            for metric, v in data.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    self.db.execute(
                        "INSERT INTO monthly_avg VALUES (?,?,?,1,?,?,?) ON CONFLICT(astronaut, month, metric) "
                        "DO UPDATE SET n=n+1, total=total+excluded.total, "
                        "vmin=min(vmin, excluded.vmin), vmax=max(vmax, excluded.vmax)",
                        (astronaut, month, metric, v, v, v))
            self.db.execute(
                "INSERT INTO monthly_status VALUES (?,?,1,?,?,0) ON CONFLICT(astronaut, month) "
                "DO UPDATE SET readings=readings+1, warn=warn+excluded.warn, crit=crit+excluded.crit",
                (astronaut, month, int(overall == 1), int(overall == 2)))
            self.db.commit()

    def monthly(self, astronaut, limit=12):
        """Середні за місяць (нові зверху): [{month, demo, readings, warn, crit, metrics:{ключ:{avg,min,max,n}}}]."""
        with self.lock:
            months = self.db.execute("SELECT month, readings, warn, crit, demo FROM monthly_status "
                                     "WHERE astronaut=? ORDER BY month DESC LIMIT ?", (astronaut, limit)).fetchall()
            rows = self.db.execute("SELECT month, metric, n, total, vmin, vmax FROM monthly_avg WHERE astronaut=?",
                                   (astronaut,)).fetchall()
        out = [{"month": m, "readings": r, "warn": w, "crit": c, "demo": bool(d), "metrics": {}}
               for m, r, w, c, d in months]
        by_month = {o["month"]: o["metrics"] for o in out}
        for month, metric, n, total, vmin, vmax in rows:
            if month in by_month and n:
                by_month[month][metric] = {"avg": round(total / n, 2), "min": vmin, "max": vmax, "n": n}
        return out

    def seed_demo(self, astronaut, base, noise, months=3):
        """Перший запуск: заповнює попередні місяці демонстраційними середніми (позначка demo=1)."""
        with self.lock:
            if self.db.execute("SELECT 1 FROM monthly_status WHERE astronaut=? AND demo=1", (astronaut,)).fetchone():
                return
            rnd = random.Random(astronaut)
            y, m = time.localtime()[:2]
            for _ in range(months):
                y, m = (y - 1, 12) if m == 1 else (y, m - 1)
                month, n = f"{y:04d}-{m:02d}", rnd.randint(2400, 2900)
                if self.db.execute("SELECT 1 FROM monthly_status WHERE astronaut=? AND month=?",
                                   (astronaut, month)).fetchone():
                    continue
                for metric, b in base.items():
                    avg = b + rnd.gauss(0, noise[metric])
                    self.db.execute("INSERT OR REPLACE INTO monthly_avg VALUES (?,?,?,?,?,?,?)",
                                    (astronaut, month, metric, n, avg * n,
                                     round(avg - 3 * noise[metric], 1), round(avg + 3 * noise[metric], 1)))
                self.db.execute("INSERT INTO monthly_status VALUES (?,?,?,?,?,1)",
                                (astronaut, month, n, rnd.randint(5, 40), rnd.randint(0, 6)))
            self.db.commit()

    def history(self, astronaut, limit=60):
        with self.lock:
            rows = self.db.execute("SELECT ts, data, overall FROM readings WHERE astronaut=? "
                                   "ORDER BY id DESC LIMIT ?", (astronaut, limit)).fetchall()
        return [{"ts": t, "data": json.loads(d), "overall": o} for t, d, o in reversed(rows)]

    def log_action(self, astronaut, text):
        with self.lock:
            self.db.execute("INSERT INTO actions(ts, astronaut, text) VALUES (?,?,?)",
                            (time.time(), astronaut, text))
            self.db.commit()

    def actions(self, astronaut, limit=10):
        with self.lock:
            rows = self.db.execute("SELECT ts, text FROM actions WHERE astronaut=? "
                                   "ORDER BY id DESC LIMIT ?", (astronaut, limit)).fetchall()
        return [{"ts": t, "text": x} for t, x in rows]

    def log_event(self, astronaut, level, text):
        with self.lock:
            self.db.execute("INSERT INTO events(ts, astronaut, level, text) VALUES (?,?,?,?)",
                            (time.time(), astronaut, level, text))
            self.db.commit()

    def events(self, limit=12):
        with self.lock:
            rows = self.db.execute("SELECT ts, level, text FROM events ORDER BY id DESC LIMIT ?",
                                   (limit,)).fetchall()
        return [{"ts": t, "level": lv, "text": x} for t, lv, x in rows]

    def say(self, lines):
        """Додає репліки переговорів: список (хто, текст, рівень)."""
        with self.lock:
            self.db.executemany("INSERT INTO dialogue(ts, speaker, text, level) VALUES (?,?,?,?)",
                                [(time.time(), who, text, level) for who, text, level in lines])
            self.db.commit()

    def dialogue(self, limit=30):
        with self.lock:
            rows = self.db.execute("SELECT id, ts, speaker, text, level FROM dialogue ORDER BY id DESC LIMIT ?",
                                   (limit,)).fetchall()
        return [{"id": i, "ts": t, "speaker": w, "text": x, "level": lv} for i, t, w, x, lv in reversed(rows)]
