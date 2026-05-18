import unittest
import dexcomCalls as sut


class MyTestCase(unittest.TestCase):

    def test_getDataFromDexcom(self):
        sut.checkDataBeforeRefresh = False
        sut.nightscoutDataPoints = 1

        data = sut.getDataFromNightscout()
        self.assertIn("current_glucose", data)
        self.assertIn("glucose_history", data)
        self.assertEqual(len(data["glucose_history"]), 1)
        self.assertIsNotNone(data["current_glucose"]["value"])
        self.assertIsNotNone(data["current_glucose"]["trend"])

    def test_getDataFromDexcomMultiple(self):
        sut.checkDataBeforeRefresh = False
        sut.nightscoutDataPoints = 10

        data = sut.getDataFromNightscout()
        self.assertEqual(len(data["glucose_history"]), 10)
        self.assertIsNotNone(data["current_glucose"]["delta"])

    def test_getDataFromDexcomNothingNew(self):
        sut.checkDataBeforeRefresh = True
        sut.nightscoutDataPoints = 1
        sut.checkFile = "lastRun"

        data = sut.getDataFromNightscout()
        self.assertEqual(len(data["glucose_history"]), 1)

        with self.assertRaises(SystemExit):
            sut.getDataFromNightscout()
