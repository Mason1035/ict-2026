import csv
import io
import unittest
from data_intake.engineering_analysis import describe, UNITS


def data(samples):
    s=io.StringIO(); w=csv.DictWriter(s,fieldnames=["kind","channel","acquisition_index","acquired_uptime_us","validity","error",*UNITS])
    w.writeheader()
    for i,(t,value,valid) in enumerate(samples):
        w.writerow({"kind":"soil","channel":0,"acquisition_index":i,"acquired_uptime_us":t,
                    "validity":valid,"error":0,"soil_raw":value})
    return s.getvalue().encode()


class EngineeringAnalysisTests(unittest.TestCase):
    def test_bins_zero_extrema_and_boundary(self):
        r=describe(data([(0,0,"Valid"),(500000,100,"Valid"),(1000000,5,"Valid")]),start_us=0)
        self.assertEqual(r["bins"][0]["minimum"],0)
        self.assertEqual(r["bins"][0]["maximum"],100)
        self.assertEqual(r["bins"][1]["bin_start_s"],1)
        self.assertEqual(r["summary"][0]["count"],3)

    def test_invalid_breaks_adjacent_pairs(self):
        r=describe(data([(0,1,"Valid"),(10,2,"Error"),(20,100,"Valid"),(30,101,"Valid")]),start_us=0)
        self.assertEqual(len(r["largest_changes"]),1)
        self.assertEqual(r["largest_changes"][0]["from_index"],2)
        self.assertEqual(len(r["exclusions"]),1)

    def test_rank_is_bounded_and_ties_earliest(self):
        r=describe(data([(0,0,"Valid"),(10,2,"Valid"),(20,0,"Valid"),(30,1,"Valid")]),start_us=0,top_n=1)
        self.assertEqual(r["largest_changes"][0]["to_index"],1)
        self.assertEqual(len(r["largest_changes"]),1)

    def test_time_reversal_and_empty_rejected(self):
        for samples in ([],[(20,1,"Valid"),(10,2,"Valid")]):
            with self.assertRaises(ValueError): describe(data(samples),start_us=0)
