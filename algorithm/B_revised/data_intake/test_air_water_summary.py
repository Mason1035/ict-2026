import unittest
from data_intake.verify_air_water_summary import checked_record

class SummaryStructureTests(unittest.TestCase):
    def test_short_record_quarantined_instead_of_shifted(self):
        self.assertIsNone(checked_record(['run','optional','count'],['AIR','240']))
    def test_extra_record_quarantined(self):
        self.assertIsNone(checked_record(['run'],['AIR','extra']))
    def test_empty_cell_preserves_alignment(self):
        self.assertEqual(checked_record(['run','optional','count'],['AIR','','240'])['count'],'240')
    def test_duplicate_header_rejected(self):
        with self.assertRaises(ValueError):checked_record(['run','run'],['a','b'])
