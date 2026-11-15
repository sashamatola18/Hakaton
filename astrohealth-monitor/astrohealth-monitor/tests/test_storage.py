import time, unittest

from astrohealth.assessment import CRIT, evaluate
from astrohealth.simulator import BASE, INCIDENTS, NOISE, SCENARIOS, Simulator
from astrohealth.storage import Storage


class MonthlyTests(unittest.TestCase):
    def setUp(self):
        self.s = Storage(":memory:")

    def test_average_min_max(self):
        for v in (60, 70, 80):
            self.s.add("A", {"heart_rate": v}, 0)
        m = self.s.monthly("A")[0]
        self.assertEqual(m["month"], time.strftime("%Y-%m"))
        self.assertEqual(m["metrics"]["heart_rate"], {"avg": 70, "min": 60, "max": 80, "n": 3})
        self.assertEqual((m["readings"], m["warn"], m["crit"]), (3, 0, 0))

    def test_months_and_astronauts_are_separate(self):
        old = time.mktime((2025, 3, 10, 12, 0, 0, 0, 0, -1))
        self.s.add("A", {"spo2": 90}, 2, ts=old)
        self.s.add("A", {"spo2": 98}, 0)
        self.s.add("B", {"spo2": 95}, 1)
        a = self.s.monthly("A")
        self.assertEqual([m["month"] for m in a], [time.strftime("%Y-%m"), "2025-03"])
        self.assertEqual(a[1]["metrics"]["spo2"]["avg"], 90)
        self.assertEqual(a[1]["crit"], 1)
        self.assertEqual(self.s.monthly("B")[0]["warn"], 1)

    def test_demo_seed_once_and_marked(self):
        self.s.seed_demo("A", BASE, NOISE)
        self.s.seed_demo("A", BASE, NOISE)
        rows = self.s.monthly("A")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["demo"] and len(r["metrics"]) == len(BASE) for r in rows))


class IncidentTests(unittest.TestCase):
    def test_incident_starts_and_ends_by_itself(self):
        sim = Simulator()
        sim.maybe_incident(chance=1)
        self.assertIn(sim.incident, INCIDENTS)
        self.assertEqual(sim.pop_started(), sim.incident)
        self.assertIsNone(sim.pop_started())
        for _ in range(25):
            sim.maybe_incident(chance=0)
        self.assertIsNone(sim.incident)

    def test_manual_scenario_blocks_incident(self):
        sim = Simulator()
        sim.inject("fatigue")
        sim.maybe_incident(chance=1)
        self.assertIsNone(sim.incident)

    def test_bad_scenarios_reach_red_zone(self):
        for name in ("tachycardia", "hypoxia", "fever", "hypotension", "hypoglycemia"):
            sim = Simulator()
            sim.inject(name)
            self.assertEqual(evaluate(sim.read())["overall"], CRIT, name)
            self.assertIn(name, SCENARIOS)


class DialogueTests(unittest.TestCase):
    CREW = ["К", "П", "Ф1", "Ф2"]
    VOC = {"К": "командире", "П": "пілоте", "Ф1": "перший", "Ф2": "другий"}

    def test_all_metrics_have_spoken_form_and_feeling(self):
        from astrohealth import dialogue
        from astrohealth.assessment import ACTIONS, METRICS
        self.assertEqual(set(dialogue.SPOKEN), set(METRICS))
        for key, sides in ACTIONS.items():
            for side in sides:
                self.assertIn((key, side), dialogue.FEEL)

    def test_lines_for_every_transition(self):
        from astrohealth import dialogue
        crit = evaluate({"heart_rate": 150, "spo2": 98})
        warn = evaluate({"heart_rate": 110})
        ok = evaluate({"heart_rate": 70})
        for prev, res, n in ((0, crit, 4), (0, warn, 2), (2, warn, 2), (2, ok, 2)):
            lines = dialogue.status_lines("Ф1", prev, res, self.CREW, self.VOC)
            self.assertEqual(len(lines), n)
            self.assertTrue(all(who in self.CREW and text and "{" not in text for who, text, _ in lines))
        self.assertIn("пульс 150", dialogue.status_lines("Ф1", 0, crit, self.CREW, self.VOC)[0][1])

    def test_routine_and_storage(self):
        from astrohealth import dialogue
        s = Storage(":memory:")
        for _ in range(20):
            s.say(dialogue.routine_lines({}, {}, {"distance_km": 314000, "percent": 71.3}, self.CREW, self.VOC))
        rows = s.dialogue()
        self.assertEqual(len(rows), 30)
        self.assertLess(rows[0]["id"], rows[-1]["id"])


if __name__ == "__main__":
    unittest.main()
