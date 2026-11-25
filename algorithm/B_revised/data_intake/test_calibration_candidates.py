import tempfile
import unittest
from pathlib import Path

from data_intake.calibration_candidates import pump_reference, run, six_face, summarize


class CalibrationCandidateTests(unittest.TestCase):
    def test_six_face_recovers_diagonal_parameters(self):
        bias = (0.25, -0.1, 0.5)
        scale = (0.9, 1.1, 1.02)
        vectors = {s+a: [bias[j]+(sign*10*scale[j] if j==i else 0) for j in range(3)]
                   for i,a in enumerate("XYZ") for s,sign in (("+",1),("-",-1))}
        result = six_face(vectors,10)
        for i,a in enumerate("XYZ"):
            self.assertAlmostEqual(result["offset_mps2"][a],bias[i])
            self.assertAlmostEqual(result["scale_dimensionless"][a],scale[i])
        self.assertAlmostEqual(result["in_sample_only"]["+Z"]["angle_to_nominal_face_deg"],0)
        vectors["+X"] = vectors["-X"]
        with self.assertRaises(ValueError): six_face(vectors,10)

    def test_single_weighing_does_not_fit_a_curve(self):
        result = pump_reference({"seconds":5,"top_area_m2":.1152,"source":"fixture",
                                 "readings":[[50,74.5,"reference"],[30,30,"unstable"]]})
        self.assertAlmostEqual(result["rows"][0]["flow_l_min_approx"],.894)
        self.assertAlmostEqual(result["rows"][0]["whole_top_area_equivalent_mm_h"],465.625)
        self.assertEqual(result["rows"][1]["role"],"unstable")
        self.assertIn("NO_CURVE",result["status"])

    def test_outlying_valid_observation_is_retained(self):
        result = summarize([(0,0),(100,1),(200,100)])
        self.assertEqual(result["n"],3)
        self.assertEqual(result["max"],100)
        self.assertEqual(result["last_minus_first_10pct_time_mean"],100)

    def test_unreviewed_archive_cannot_reuse_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"test.zip"
            path.write_bytes(b"another batch")
            with self.assertRaisesRegex(ValueError,"哈希"):
                run(path,{"archive_sha256":"incorrect"})
