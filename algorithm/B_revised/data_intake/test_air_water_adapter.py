import copy,unittest
from data_intake.air_water_adapter import evaluate_observation,load_parameters

class AdapterTests(unittest.TestCase):
    def evaluate(self,**kw):
        args=dict(channel=2,raw=20606,valid=True,firmware_sha256=load_parameters()['firmware_elf_sha256']);args.update(kw)
        return evaluate_observation(**args)
    def test_supported_channel_and_safety(self):
        r=self.evaluate();self.assertEqual(r['w_rel_pct'],0);self.assertIsNone(r['vwc_pct']);self.assertFalse(r['risk_eligible']);self.assertFalse(r['fusion_eligible'])
    def test_unknown_firmware_never_evaluated(self):
        r=self.evaluate(firmware_sha256=None);self.assertIsNone(r['w_rel_pct']);self.assertIn('FIRMWARE_NOT_APPLICABLE',r['quality_flags'])
    def test_invalid_sample_never_evaluated(self):
        self.assertIsNone(self.evaluate(valid=False)['w_rel_pct'])
    def test_null_stays_null(self):
        self.assertIsNone(self.evaluate(raw=None)['w_rel_pct'])
    def test_config_change_rejected_without_mutation(self):
        p=load_parameters();original=copy.deepcopy(p);self.evaluate(parameters=p);self.assertEqual(p,original)
        p['parameters']['2']['raw_air']+=1
        with self.assertRaises(ValueError):self.evaluate(parameters=p)
    def test_flags_and_units(self):
        r=self.evaluate(raw=0);self.assertEqual(r['w_rel_pct'],100);self.assertEqual(r['quality_flags'],['CLIPPED']);self.assertEqual(r['unit'],'air_water_relative_percent')

if __name__=='__main__':unittest.main()
