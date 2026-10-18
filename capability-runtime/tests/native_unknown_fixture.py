"""Assertions for unproved scoped rejection: immutable evidence, never a retry license."""
import gzip
import json


def assert_unknown_refusal(test, result):
    test.assertEqual(result['state'], 'unknown', result)
    test.assertEqual(result['effect_certainty'], 'unknown')
    test.assertEqual(result['cleanup_certainty'], 'unknown')
    receipts = [json.loads(gzip.decompress(p.read_bytes()))
                for p in (test.root / 'runtime').glob('receipt-*.json.gz')]
    uncertain = [r for r in receipts if r.get('status') == 'uncertain']
    test.assertEqual(len(uncertain), 1, receipts)
    receipt = uncertain[0]
    test.assertTrue(receipt['action_id'])
    test.assertTrue(receipt['queue_request_id'])
    test.assertEqual(receipt['queue_session_id'], test.resident.session_id)
    test.assertTrue(test.resident.active.capability_unknown)
    test.assertEqual(test.resident.active.action_id, receipt['action_id'])
    test.assertIsNotNone(test.client.session()['capability_lease'])
    test.assertFalse([p for p, _ in test.bridge.posts
                      if p in ('/control/action', '/control/action/cancel')])
    return receipt
