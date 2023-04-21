import unittest
import dexcomCalls as sut

class MyTestCase(unittest.TestCase):
        
    def test_getDataFromNS(self):
        sut.checkDataBeforeRefresh = False
        sut.nightscoutDataPoints = 1

        sgvs, dates, delta = sut.getDataFromNightscout()
        self.assertEqual(len(sgvs), 1)
        self.assertEqual(len(dates), 1)
        self.assertIsNotNone(delta)
    
    def test_getDataFromNSMultiple(self):
        sut.checkDataBeforeRefresh = False
        sut.nightscoutDataPoints = 10

        sgvs, dates, delta = sut.getDataFromNightscout()
        self.assertEqual(len(sgvs), 10)
        self.assertEqual(len(dates), 10)
        self.assertIsNotNone(delta)

    def test_getDataFromNSNothingNew(self):
        sut.checkDataBeforeRefresh = True
        sut.nightscoutDataPoints = 1
        sut.checkFile = "lastRun"

        sgvs, dates, delta = sut.getDataFromNightscout()
        self.assertEqual(len(sgvs), 1)
        self.assertEqual(len(dates), 1)
        self.assertIsNotNone(delta)

        with self.assertRaises(SystemExit): 
            sut.getDataFromNightscout()
