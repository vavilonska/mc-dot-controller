import unittest
from capacity_model import measurement

class CapacityTests(unittest.TestCase):
    def test_actual94_projected256_shape_not_unlimited_capacity(self):
        report=measurement();self.assertEqual(report['actual94_bytes'],2482698)
        self.assertEqual(report['max_bytes'],8388608);self.assertEqual(report['reserve_bytes'],393216)
        for projection in report['projections'].values():self.assertEqual(projection['records'],256)
        self.assertFalse(report['projections']['maximum']['fits_with_reserve'])
        self.assertTrue(report['projections']['median']['fits_with_reserve'])

if __name__=='__main__':unittest.main()
