import unittest,copy
from data_intake.vwc_trial_20261124 import evaluate_trial,load_parameters

class TrialTests(unittest.TestCase):
 def test_all_nine_knots(self):
  for ch,p in load_parameters()['channels'].items():
   for point in p['points']:
    r=evaluate_trial(int(ch),point['raw']);self.assertAlmostEqual(r['vwc_est_pct'],point['vwc_est_pct']);self.assertTrue(r['in_range']);self.assertFalse(r['risk_eligible'])
 def test_piecewise_midpoints(self):
  for ch,p in load_parameters()['channels'].items():
   for a,b in zip(p['points'],p['points'][1:]):
    self.assertAlmostEqual(evaluate_trial(int(ch),(a['raw']+b['raw'])/2)['vwc_est_pct'],(a['vwc_est_pct']+b['vwc_est_pct'])/2)
 def test_outside_is_flagged_not_extrapolated(self):
  for ch in range(3):
   for raw,want in [(32767,0),(-32768,20.9)]:
    r=evaluate_trial(ch,raw);self.assertEqual(r['vwc_est_pct'],want);self.assertFalse(r['in_range']);self.assertIn('VWC_OUT_OF_CALIBRATION_RANGE_CLIPPED',r['flags'])
 def test_missing_not_zero(self):self.assertIsNone(evaluate_trial(0,None)['vwc_est_pct'])
 def test_invalid_rejected(self):
  for value in (True,'1',float('nan'),float('inf'),40000):
   with self.assertRaises(ValueError):evaluate_trial(0,value)
  with self.assertRaises(ValueError):evaluate_trial(True,20000)
 def test_metrics_versions_distinct_and_input_unchanged(self):
  p=load_parameters();before=copy.deepcopy(p);r=evaluate_trial(0,19871,p)
  self.assertEqual(p,before);self.assertNotEqual(r['w_rel_pct'],r['vwc_est_pct']);self.assertNotEqual(r['w_rel_calibration_version'],r['vwc_calibration_version']);self.assertEqual(r['soil_raw'],19871)
 def test_bad_order_rejected(self):
  p=load_parameters();p['channels']['0']['points'].reverse()
  with self.assertRaises(ValueError):evaluate_trial(0,20000,p)
