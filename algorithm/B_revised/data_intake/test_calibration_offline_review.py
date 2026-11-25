import unittest

from data_intake.calibration_offline_review import face_check, gyro_time_holdout, repeat_holdout


class OfflineCalibrationReviewTests(unittest.TestCase):
    def test_gyro_holdout_does_not_fit_with_held_out_values(self):
        r = gyro_time_holdout([(0,2),(1,2),(2,5),(3,5)])
        self.assertEqual(r["fit_bias_dps"],2)
        self.assertEqual(r["held_out_corrected_mean_dps"],3)
        self.assertEqual(r["held_out_corrected_rms_dps"],3)
        self.assertEqual(r["fit_count"],2)
        self.assertEqual(r["test_count"],2)

    def test_gyro_rejects_reordered_samples(self):
        with self.assertRaises(ValueError):
            gyro_time_holdout([(0,2),(2,2),(1,5),(3,5)])

    def test_face_metrics_keep_raw_and_signed_orientation(self):
        p={"offset_mps2":{"X":0,"Y":0,"Z":1},"scale_dimensionless":{"X":1,"Y":1,"Z":2}}
        r=face_check([0,0,-19],p,"-Z",10)
        self.assertEqual(r["raw"]["norm_error_mps2"],9)
        self.assertEqual(r["corrected"]["norm_error_mps2"],0)
        self.assertEqual(r["corrected"]["angle_to_nominal_deg"],0)

    def test_soil_repeat_is_not_part_of_its_reference(self):
        runs=[{"member":str(i),"mean":v} for i,v in enumerate((100,110,150))]
        r=repeat_holdout(runs)
        self.assertEqual(r[2]["reference_members"],["0","1"])
        self.assertEqual(r[2]["difference_adc"],45)
        with self.assertRaises(ValueError): repeat_holdout([runs[0]]*3)
