"""Cross-slice retained leases remain barriers at cleanup's final pure fence."""
import unittest
import test_cleanup_release_fences as release

class IntegratedCleanupOwnerTests(unittest.TestCase):
    def test_same_lease_foreign_binding_during_last_io_refuses_release(self):
        for field in ('external_navigation','managed_navigation'):
            for boundary in ('checkpoint','session'):
                for binding in ({},{'state':'unknown'},{'state':'stopping'}):
                    with self.subTest(field=field,boundary=boundary,binding=binding):
                        gateway=release.Gateway();marker=dict(binding)
                        if boundary=='checkpoint':gateway.callback=lambda _:gateway.old.__setitem__(field,marker)
                        else:gateway.q.callback=lambda call:gateway.old.__setitem__(field,marker) if call==1 else None
                        result=gateway.release()
                        self.assertEqual(result['status'],'uncertain')
                        self.assertIs(gateway.capability_lease,gateway.old)
                        self.assertIs(gateway.old[field],marker)
                        self.assertEqual(len(gateway.checkpoints),1)
                        self.assertIsNotNone(gateway.checkpoints[0])
                        self.assertTrue(gateway.handoff_latched)
