"""Імітація датчиків. Замініть на читання реальних пристроїв."""
import random, time

# Типові значення здорової людини в польоті та природний розкид вимірів
BASE = {"heart_rate": 68, "spo2": 97.5, "systolic": 118, "diastolic": 76, "temperature": 36.7,
        "resp_rate": 15, "glucose": 5.2, "co2": 2.0, "radiation": 1.0, "sleep": 7.0}
NOISE = {"heart_rate": 3, "spo2": 0.4, "systolic": 3, "diastolic": 2.5, "temperature": 0.1,
         "resp_rate": 0.8, "glucose": 0.2, "co2": 0.12, "radiation": 0.05, "sleep": 0.05}
SCENARIOS = {
    "tachycardia": {"heart_rate": 145},
    "hypoxia": {"spo2": 87, "resp_rate": 24, "heart_rate": 108},
    "co2": {"co2": 4.2},
    "radiation": {"radiation": 6.0},
    "fatigue": {"sleep": 4.5, "heart_rate": 96, "temperature": 37.6},
    "fever": {"temperature": 39.4, "heart_rate": 112, "resp_rate": 22},
    "hypotension": {"systolic": 70, "diastolic": 42, "heart_rate": 106},
    "hypoglycemia": {"glucose": 2.1, "heart_rate": 104},
}
DRIFTS = {"creep": {"heart_rate": 2.5}}  # зміна за кожен вимір
SCENARIO_NAMES = {  # порядок = порядок кнопок і клавіш Shift+1…
    "creep": "Повільне зростання пульсу", "tachycardia": "Тахікардія", "hypoxia": "Гіпоксія",
    "co2": "Підвищений CO₂", "radiation": "Сплеск радіації", "fatigue": "Втома і безсоння",
    "fever": "Гарячка", "hypotension": "Падіння тиску", "hypoglycemia": "Низька глюкоза",
}
# Випадкові погіршення стану: що може статися само собою і як довго триває (у вимірах)
INCIDENTS = ("tachycardia", "hypoxia", "fever", "hypotension", "hypoglycemia", "fatigue")
INCIDENT_CHANCE = 0.006          # імовірність початку за один вимір одного астронавта
LIVE_TIMEOUT = 12                # секунд без нових даних, після яких датчик вважається відключеним
INCIDENT_LENGTH = (10, 20)       # тривалість, вимірів (при 2 с між вимірами — 20–40 с)


class Simulator:
    def __init__(self):
        self.override, self.drift, self.offset, self.scenario = {}, {}, {}, None
        self.incident, self.left, self.started = None, 0, None
        self.live = {}  # показник → (значення, час, джерело): дані зі справжнього датчика

    def set_live(self, values, source):
        """Значення зі справжнього датчика заміняють симульовані, доки датчик на зв'язку."""
        now = time.time()
        for key, value in values.items():
            self.live[key] = (value, now, source)

    def live_sources(self, max_age=LIVE_TIMEOUT):
        """Показники, для яких є свіжі дані датчика: {показник: джерело}."""
        now = time.time()
        return {k: src for k, (_, ts, src) in self.live.items() if now - ts <= max_age}

    def inject(self, scenario):
        if scenario != "reset" and scenario not in SCENARIOS and scenario not in DRIFTS:
            raise ValueError(f"Невідомий сценарій: {scenario}")
        self.override = dict(SCENARIOS.get(scenario, {}))
        self.drift, self.offset = dict(DRIFTS.get(scenario, {})), {}
        self.scenario = None if scenario == "reset" else scenario
        self.incident, self.left = None, 0

    def maybe_incident(self, chance=INCIDENT_CHANCE):
        """Випадкове погіршення: починається само, минає само. Не заважає ручним сценаріям."""
        if self.incident:
            self.left -= 1
            if self.left <= 0:
                self.incident = None
        elif self.scenario is None and random.random() < chance:
            self.incident, self.left = random.choice(INCIDENTS), random.randint(*INCIDENT_LENGTH)
            self.started = self.incident  # сервер забере це для журналу подій

    def pop_started(self):
        started, self.started = self.started, None
        return started

    def read(self):
        for k, step in self.drift.items():
            self.offset[k] = self.offset.get(k, 0) + step
        override = SCENARIOS[self.incident] if self.incident else self.override
        target = {k: v + self.offset.get(k, 0) for k, v in {**BASE, **override}.items()}
        out = {k: round(v + random.gauss(0, NOISE[k]), 1) for k, v in target.items()}
        out["spo2"] = min(out["spo2"], 100)
        for k in ("heart_rate", "systolic", "diastolic", "resp_rate"):  # ці датчики дають цілі числа
            out[k] = int(round(out[k]))
        out["sleep"], out["radiation"] = max(out["sleep"], 0), max(out["radiation"], 0)
        for key in self.live_sources():          # справжній датчик має перевагу над симуляцією
            out[key] = self.live[key][0]
        return out


# Кабіна: земна атмосфера (101,3 кПа, 21 % кисню); CO₂ 2 мм рт.ст. ≈ 2600 ppm; радіація 1 мЗв/добу ≈ 42 мкЗв/год
CABIN_BASE = {"temp": 22.5, "pressure": 101.3, "oxygen": 21.0, "co2": 2600, "radiation": 42}
CABIN_NOISE = {"temp": 0.25, "pressure": 0.3, "oxygen": 0.1, "co2": 90, "radiation": 2}
CABIN_SCENARIOS = {"co2": {"co2": 5500}, "radiation": {"radiation": 250}}


class CabinSimulator:
    """Імітація датчиків кабіни (спільні для всього екіпажу)."""

    def __init__(self):
        self.override = {}

    def inject(self, scenario):
        self.override = dict(CABIN_SCENARIOS.get(scenario, {}))

    def read(self):
        target = {**CABIN_BASE, **self.override}
        out = {k: round(v + random.gauss(0, CABIN_NOISE[k]), 1) for k, v in target.items()}
        out["co2"] = int(out["co2"])
        return out
