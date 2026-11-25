import unittest
from data_intake.air_water_20261122 import relative_percent

class AirWaterTests(unittest.TestCase):
    p={str(i):{'raw_air':a,'raw_water':w} for i,(a,w) in enumerate([(20718,13032),(20945,13118),(20606,13004)])}
    def test_three_channel_endpoints(self):
        for i in range(3):
            c=self.p[str(i)]
            self.assertEqual(relative_percent(i,c['raw_air'],self.p)['value'],0)
            self.assertEqual(relative_percent(i,c['raw_water'],self.p)['value'],100)
    def test_missing_is_not_dry(self):
        self.assertIsNone(relative_percent(2,None,self.p)['value'])
    def test_clipping_keeps_flag(self):
        self.assertEqual(relative_percent(0,30000,self.p)['flags'],['CLIPPED'])
    def test_invalid_input_rejected(self):
        for value in (True,float('nan'),float('inf'),40000,'20000'):
            with self.assertRaises(ValueError):relative_percent(0,value,self.p)
        for channel in (True,'0',3,-1):
            with self.assertRaises(ValueError):relative_percent(channel,20000,self.p)
    def test_bad_endpoints_rejected(self):
        with self.assertRaises(ValueError):relative_percent(0,20,{'0':{'raw_air':10,'raw_water':10}})

if __name__=='__main__':unittest.main()
