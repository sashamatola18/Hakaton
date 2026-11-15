import unittest
from astrohealth.assessment import CRIT, OK, WARN, cabin_actions, detect_trends, evaluate, evaluate_cabin


class AssessmentTests(unittest.TestCase):
    def test_normal(self):
        r = evaluate({"heart_rate": 70, "spo2": 98, "sleep": 7})
        self.assertEqual(r["overall"], OK)

    def test_warning(self):
        self.assertEqual(evaluate({"heart_rate": 110})["overall"], WARN)

    def test_critical_has_action_first(self):
        r = evaluate({"spo2": 88, "heart_rate": 105})
        self.assertEqual(r["overall"], CRIT)
        self.assertEqual(r["actions"][0]["level"], CRIT)

    def test_three_warnings_escalate(self):
        r = evaluate({"heart_rate": 105, "sleep": 5, "co2": 4.5, "spo2": 98})
        self.assertEqual(r["overall"], CRIT)

    def test_trend_detected(self):
        hist = [{"heart_rate": 72 + 3 * i} for i in range(8)]
        self.assertEqual(len(detect_trends(hist)), 1)

    def test_stable_has_no_trend(self):
        hist = [{"heart_rate": 72 + (i % 2)} for i in range(10)]
        self.assertEqual(detect_trends(hist), [])

    def test_cabin_co2_warning(self):
        items = evaluate_cabin({"co2": 6500, "oxygen": 21.5})
        self.assertEqual({i["key"]: i["level"] for i in items}, {"co2": WARN, "oxygen": OK})

    def test_cabin_actions(self):
        acts = cabin_actions(evaluate_cabin({"co2": 12000, "oxygen": 21.5}))
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["level"], CRIT)

    def test_thresholds_follow_published_norms(self):
        cases = [("spo2", 95, OK), ("spo2", 94, WARN), ("spo2", 89, CRIT),
                 ("systolic", 139, OK), ("systolic", 140, WARN), ("systolic", 181, CRIT), ("systolic", 89, WARN),
                 ("diastolic", 89, OK), ("diastolic", 90, WARN), ("diastolic", 121, CRIT),
                 ("glucose", 3.9, OK), ("glucose", 3.8, WARN), ("glucose", 2.9, CRIT), ("glucose", 14, CRIT),
                 ("co2", 3.0, OK), ("co2", 3.1, WARN), ("co2", 5.4, CRIT),
                 ("resp_rate", 12, OK), ("resp_rate", 21, WARN), ("heart_rate", 100, OK), ("heart_rate", 101, WARN)]
        for key, value, level in cases:
            self.assertEqual(evaluate({key: value})["overall"], level, (key, value))

    def test_unknown_metric_ignored(self):
        self.assertEqual(evaluate({"foo": 1})["items"], [])


if __name__ == "__main__":
    unittest.main()
