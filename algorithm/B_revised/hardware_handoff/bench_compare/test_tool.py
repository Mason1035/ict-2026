import copy
import tempfile
import unittest
from pathlib import Path
from hardware_handoff.bench_compare.tool import differences, validate_risks, load, generate

class CompareTests(unittest.TestCase):
    def test_null_bool_and_mask_exact(self):
        for a,b in [(None,0),(True,1),({"reason_mask":1},{"reason_mask":1.0}),({"reason_mask":1},{"reason_mask":2})]:
            self.assertTrue(differences(a,b))
    def test_tolerance(self):
        self.assertFalse(differences({"sensor_score":30.0},{"sensor_score":30.0001}))
        self.assertTrue(differences({"sensor_score":30.0},{"sensor_score":30.1}))
    def test_boundary_cannot_hide_in_tolerance(self):
        ref={"sensor_score":30.,"level":"WATCH","reason_mask":None}
        actual={**ref,"sensor_score":29.9999}
        self.assertFalse(differences(ref,actual))
        self.assertTrue(validate_risks(actual))
    def test_structure_and_nonfinite(self):
        self.assertTrue(differences({"a":1},{"a":1,"extra":2}))
        self.assertTrue(differences([1],[1,2]))
        self.assertTrue(differences(0,float("nan")))
        self.assertTrue(validate_risks({"sensor_score":None,"level":"NORMAL","reason_mask":None}))
    def test_strict_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.json"
            for text in ['{"x":1,"x":2}', '{"x":NaN}']:
                p.write_text(text)
                with self.assertRaises(ValueError):load(p)
    def test_generate_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"vectors"
            generate(p)
            expected=load(p/"expected.json")
            self.assertFalse(differences(expected,copy.deepcopy(expected)))
            self.assertFalse(validate_risks(expected))
            self.assertEqual(len(expected["cases"]),3)
            self.assertEqual(len(load(p/"binary64_boundaries.json")["vectors"]),15)
            with self.assertRaises(FileExistsError):generate(p)

if __name__=="__main__":unittest.main()
