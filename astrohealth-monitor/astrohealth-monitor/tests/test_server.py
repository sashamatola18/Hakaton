"""Перевірка HTTP API на справжньому сервері (тимчасова база, випадковий порт)."""
import json, os, tempfile, threading, unittest, urllib.error, urllib.parse, urllib.request

_tmp = tempfile.TemporaryDirectory()
os.environ["ASTROHEALTH_DB"] = os.path.join(_tmp.name, "test.db")

from astrohealth import server  # noqa: E402  (імпорт після налаштування бази)

NAME = "Матола О."


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = server.make_server(0, sim=False)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, data=data)) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def json(self, path, body=None, raw=None):
        code, data, _ = self.call(path, body, raw)
        return code, json.loads(data)

    def setUp(self):
        self.json("/api/control", {"action": "reset"})

    def test_page_and_meta(self):
        code, html, _ = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn("AstroHealth", html.decode())
        code, meta = self.json("/api/meta")
        self.assertEqual(set(meta["metrics"]), set(server.METRICS))

    def test_crew_has_all_vitals(self):
        code, crew = self.json("/api/crew")
        self.assertEqual([c["astronaut"] for c in crew], list(server.CREW))
        for c in crew:
            self.assertEqual({i["key"] for i in c["items"]}, set(server.METRICS))

    def test_cabin(self):
        code, cab = self.json("/api/cabin")
        self.assertEqual(len(cab["items"]), 5)
        self.assertTrue(0 <= cab["mission"]["percent"] <= 100)

    def test_manual_reading_merges_with_last(self):
        code, r = self.json("/api/readings", {"astronaut": NAME, "values": {"heart_rate": "150"}})
        self.assertEqual(code, 200)
        self.assertEqual(r["overall"], 2)
        self.assertEqual(len(r["items"]), len(server.METRICS))  # решта показників не зникла
        self.assertEqual(next(i for i in r["items"] if i["key"] == "heart_rate")["side"], "high")

    def test_manual_reading_rejects_bad_input(self):
        for values in ({}, {"heart_rate": ""}, {"heart_rate": "abc"}, {"heart_rate": 9999},
                       {"heart_rate": "NaN"}, {"foo": 1}, {"spo2": 120}, [1, 2]):
            code, r = self.json("/api/readings", {"astronaut": NAME, "values": values})
            self.assertEqual(code, 400, values)
            self.assertTrue(r["error"])
        code, crew = self.json("/api/crew")  # картка не зіпсована
        self.assertEqual(len(crew[0]["items"]), len(server.METRICS))

    def test_bad_requests_do_not_crash(self):
        self.assertEqual(self.json("/api/readings", raw=b"{oops")[0], 400)
        self.assertEqual(self.json("/api/readings", raw=b"[1,2]")[0], 400)
        self.assertEqual(self.json("/api/readings", {"astronaut": "Хтось", "values": {"spo2": 97}})[0], 400)
        self.assertEqual(self.json("/api/simulate", {"astronaut": NAME, "scenario": "nope"})[0], 400)
        self.assertEqual(self.json("/api/control", {"action": "explode"})[0], 400)
        self.assertEqual(self.json("/api/actions", {"astronaut": NAME, "text": "   "})[0], 400)
        self.assertEqual(self.json("/api/history?astronaut=nobody")[0], 400)
        self.assertEqual(self.json("/api/nothing")[0], 404)
        self.assertEqual(self.json("/photos/99")[0], 404)
        self.assertEqual(self.json("/api/crew")[0], 200)  # сервер живий

    def test_scenario_and_reset(self):
        code, r = self.json("/api/simulate", {"astronaut": NAME, "scenario": "hypoxia"})
        self.assertEqual((r["overall"], r["scenario"]), (2, "hypoxia"))
        self.json("/api/control", {"action": "reset"})
        code, crew = self.json("/api/crew")
        self.assertTrue(all(c["scenario"] is None for c in crew))

    def test_cabin_scenario_shared_between_crew(self):
        other = list(server.CREW)[1]
        self.json("/api/simulate", {"astronaut": NAME, "scenario": "co2"})
        self.json("/api/simulate", {"astronaut": other, "scenario": "reset"})  # чужий «скинути» не чіпає кабіну
        co2 = lambda: next(i for i in self.json("/api/cabin")[1]["items"] if i["key"] == "co2")
        self.assertGreaterEqual(co2()["level"], 1)
        self.json("/api/simulate", {"astronaut": NAME, "scenario": "reset"})
        self.assertEqual(co2()["level"], 0)

    def test_pause_resume(self):
        self.assertTrue(self.json("/api/control", {"action": "pause"})[1]["paused"])
        self.assertTrue(self.json("/api/cabin")[1]["paused"])
        self.assertFalse(self.json("/api/control", {"action": "resume"})[1]["paused"])

    def test_actions_log_and_events(self):
        code, log = self.json("/api/actions", {"astronaut": NAME, "text": "Пульс: відпочив <b>"})
        self.assertEqual(log[0]["text"], "Пульс: відпочив <b>")
        self.assertTrue(self.json("/api/events")[1])

    def test_devices_named_for_every_metric(self):
        code, crew = self.json("/api/crew")
        serials = set()
        for c in crew:
            for i in c["items"]:
                self.assertTrue(i["device"]["name"] and i["device"]["serial"])
                serials.add(i["device"]["serial"])
        models = {code for _, code, _ in server.DEVICES.values()}      # тонометр дає два показники
        self.assertEqual(len(serials), len(crew) * len(models))        # у кожного свій комплект
        code, cab = self.json("/api/cabin")
        self.assertTrue(all(i["device"]["name"] for i in cab["items"]))
        code, r = self.json("/api/readings", {"astronaut": NAME, "values": {"spo2": 97}})
        self.assertEqual([i["key"] for i in r["items"] if i["manual"]], ["spo2"])

    def test_monthly_average_updates(self):
        import time
        q = "/api/monthly?astronaut=" + urllib.parse.quote(NAME)
        month = time.strftime("%Y-%m")
        before = next(m for m in self.json(q)[1] if m["month"] == month)
        self.json("/api/readings", {"astronaut": NAME, "values": {"heart_rate": 150}})
        after = next(m for m in self.json(q)[1] if m["month"] == month)
        self.assertEqual(after["readings"], before["readings"] + 1)
        self.assertEqual(after["crit"], before["crit"] + 1)
        self.assertEqual(after["metrics"]["heart_rate"]["max"], 150)
        self.assertGreater(after["metrics"]["heart_rate"]["avg"], before["metrics"]["heart_rate"]["avg"])
        self.assertFalse(after["demo"])
        self.assertTrue(any(m["demo"] for m in self.json(q)[1]))  # попередні місяці — демо
        code, data, headers = self.call("/api/export-monthly?astronaut=" + urllib.parse.quote(NAME))
        self.assertIn(month, data.decode("utf-8-sig"))

    def test_new_bad_state_scenarios_are_critical(self):
        for sc in ("fever", "hypotension", "tachycardia", "hypoxia", "hypoglycemia"):
            code, r = self.json("/api/simulate", {"astronaut": NAME, "scenario": sc})
            self.assertEqual(r["overall"], 2, sc)

    def test_incidents_toggle(self):
        self.assertTrue(self.json("/api/control", {"action": "incidents_on"})[1]["incidents"])
        self.assertFalse(self.json("/api/control", {"action": "incidents_off"})[1]["incidents"])

    def test_crew_talks_about_critical_state(self):
        other = list(server.CREW)[2]
        self.json("/api/readings", {"astronaut": other, "values": {"spo2": 86}})
        code, lines = self.json("/api/dialogue")
        tail = lines[-4:]
        self.assertEqual([l["level"] for l in tail], [2, 2, 2, 2])
        self.assertEqual(tail[0]["speaker"], NAME)        # командир питає
        self.assertEqual(tail[1]["speaker"], other)       # хворий відповідає
        self.assertIn("сатурація 86", tail[0]["text"])
        self.assertGreaterEqual(len({l["speaker"] for l in tail}), 3)

    def test_commander_ill_pilot_leads(self):
        self.json("/api/simulate", {"astronaut": NAME, "scenario": "fever"})
        code, lines = self.json("/api/dialogue")
        self.assertEqual(lines[-4]["speaker"], list(server.CREW)[1])
        self.assertIn("температура", lines[-4]["text"])

    def test_female_crew_member_speaks_in_feminine(self):
        woman = next(iter(server.FEMALE))
        self.json("/api/readings", {"astronaut": woman, "values": {"heart_rate": 112}})
        self.json("/api/actions", {"astronaut": woman, "text": "Викликано лікаря польоту. Стан: увага"})
        code, lines = self.json("/api/dialogue")
        self.assertEqual((lines[-1]["speaker"], lines[-1]["text"]), (woman, "Прийняла, чекаю на лікаря."))
        self.assertEqual(self.json("/api/meta")[1]["female"].count(True), 1)

    def test_user_line_and_reply(self):
        code, lines = self.json("/api/dialogue", {"astronaut": NAME, "text": "Перевірка зв'язку <b>"})
        self.assertEqual((lines[-2]["speaker"], lines[-2]["text"]), (NAME, "Перевірка зв'язку <b>"))
        self.assertNotEqual(lines[-1]["speaker"], NAME)
        self.assertEqual(self.json("/api/dialogue", {"astronaut": NAME, "text": " "})[0], 400)

    def test_profile_for_every_crew_member(self):
        code, crew = self.json("/api/crew")
        calls = {c["profile"]["callsign"] for c in crew}
        self.assertEqual(len(calls), len(crew))
        for c in crew:
            for field in ("specialty", "duties", "emergency", "missions", "space_hours", "blood", "allergies"):
                self.assertIn(field, c["profile"])
            self.assertIn("Rh", c["profile"]["blood"])
            self.assertNotEqual(c["profile"]["allergies"], "не вказано")

    def test_healthy_crew_stays_green(self):
        """Звичайні значення симуляції не повинні випадково потрапляти в «увагу»."""
        bad = 0
        for _ in range(400):
            r = server.evaluate(server.Simulator().read())
            bad += r["overall"] != 0
        self.assertLessEqual(bad, 8)
        cab = sum(any(i["level"] for i in server.evaluate_cabin(server.CabinSimulator().read())) for _ in range(400))
        self.assertEqual(cab, 0)

    def test_mission_matches_real_flight(self):
        m = self.json("/api/cabin")[1]["mission"]
        self.assertEqual(m["duration_s"], 9 * 86400 + 3600 + 32 * 60)
        self.assertLessEqual(m["distance_km"], 406_771)
        self.assertEqual(m["elapsed_s"] + m["remaining_s"], m["duration_s"])
        self.assertTrue(all(v["source"] for v in self.json("/api/meta")[1]["metrics"].values()))

    def test_export_csv(self):
        code, data, headers = self.call("/api/export?astronaut=" + urllib.parse.quote(NAME))
        self.assertEqual(code, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        lines = data.decode("utf-8-sig").splitlines()
        self.assertEqual(lines[0].split(",")[0], "time")
        self.assertGreater(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
