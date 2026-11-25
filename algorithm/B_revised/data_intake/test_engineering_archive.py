import csv
import io
import unittest
import zlib

from data_intake.engineering_archive import inspect_capture


def example():
    s = io.StringIO(newline="")
    s.write("# NODE01_ENGINEERING_DIAGNOSTIC_V1\n")
    writer = csv.writer(s)
    writer.writerow(["kind", "channel", "acquisition_index", "acquired_uptime_us", "validity", "error",
                     "soil_raw", "gx_dps", "gy_dps", "gz_dps"])
    for i, (kind, channel) in enumerate((("imu",0),("imu",1),("soil",0),("soil",1),("soil",2))):
        writer.writerow([kind,channel,i,100+i,"Valid",0,0,0,0,0])
    data=s.getvalue().encode()
    begin={"experiment_id":"TEST_ONLY", "elf_sha256":"TEST_FW"}
    end={**begin,"accepted":5,"verified_rows":5,"csv_bytes":len(data),
         "csv_crc32":f"{zlib.crc32(data)&0xffffffff:08x}","csv_verified":True,"storage_clean":True,
         "start_us":100,"stop_us":200,"actual_duration_us":100,"top_valid":1,"toe_valid":1,"soil_valid":[1,1,1],
         **{k:0 for k in ("queue_drop","internal_drop","errors","uncertain","replay","i2c_errors","lock_timeouts","sensor_errors")}}
    return data,begin,end


class EngineeringArchiveTests(unittest.TestCase):
    def test_zero_preserved_and_no_training_approval(self):
        r=inspect_capture(*example())
        self.assertEqual(r["engineering_integrity"],"CHECKED")
        self.assertEqual(r["channels"]["soil_0"]["raw_min"],0)
        self.assertFalse(r["formal_training_ready"])

    def test_tampered_crc_count_and_identity_reported(self):
        data,b,e=example()
        e.update(csv_crc32="00000000",accepted=6,experiment_id="OTHER")
        r=inspect_capture(data,b,e)
        self.assertTrue({"CRC32_MISMATCH","ACCEPTED_MISMATCH","EXPERIMENT_ID_MISMATCH"} <= set(r["issues"]))

    def test_unrecognized_csv_is_not_silently_adapted(self):
        with self.assertRaises(ValueError):
            inspect_capture(b"node_id,sequence\nA,1\n",{}, {})
