"""Real IPC loops against a synthetic20TPS callback/strict admission endpoint.

These are measured offline adapter outcomes, not native game latency guarantees.
The separate actual-JAR tests prove the native guard/encoder implementation.
"""
from copy import deepcopy
import time
import json
import unittest

from resident_controller.transport import BridgeError
import test_gateway_integration as gateway_chain
from test_gateway_integration import EndpointFixture


class TickBoundEndpoint(EndpointFixture):
    def __init__(self, extra_admission_delay=0.):
        super().__init__()
        self.origin = time.monotonic()
        self.extra_admission_delay = extra_admission_delay
        self.admissions = []
        self.http_reads = []

    def game_tick(self):return 200+int((time.monotonic()-self.origin)/.05)

    def snapshot(self):
        value = super().snapshot()
        self.tick = self.game_tick()
        value['world']['game_time'] = self.tick
        value['capability_guard'] = {'schema_version':1,'source_tick':self.tick,
                                     'source_nano':str(time.monotonic_ns())}
        return value

    def request(self, method, path, body=None):
        # One request costs one50ms native callback, not one instant fake call.
        time.sleep(.05)
        if method == 'GET':self.http_reads.append(path)
        if path == '/control/action':
            if self.extra_admission_delay:time.sleep(self.extra_admission_delay)
            guard=body['capability_guard'];nano=time.monotonic_ns();tick=self.game_tick()
            age=nano-int(guard['source_nano']);delta=tick-guard['source_tick']
            details={'schema_version':1,'phase':'guard_start','source_tick':guard['source_tick'],
                'current_tick':tick,'tick_delta':delta,'source_nano':guard['source_nano'],
                'current_nano':str(nano),'elapsed_nanos':str(age),'max_elapsed_nanos':'800000000',
                'max_tick_delta':5,'nano_age_negative':age<0,'nano_age_exceeded':age>800000000,
                'tick_reversed':delta<0,'tick_delta_exceeded':delta>5}
            self.admissions.append(deepcopy(details))
            if any(details[k] for k in ('nano_age_negative','nano_age_exceeded','tick_reversed','tick_delta_exceeded')):
                self.posts.append((path,deepcopy(body)))
                raise BridgeError('capability_source_expired',status=409,uncertain=False,
                                  capability_source_freshness=details,capability_source_freshness_status='valid')
        return super().request(method,path,body)


class CapabilityTurnaroundTests(unittest.TestCase):
    def run_case(self,delay,mode):
        bridge=TickBoundEndpoint(delay)
        result=gateway_chain.GatewayChainTests.run_chain(self,mode,bridge=bridge,resident_interval=.05)
        self.assertEqual(len(bridge.admissions),1,'never retry the submitted action')
        if mode=='reject':
            self.assertEqual(result.evidence['submission_outcome'],'known_no_effect_rejection')
            self.assertEqual(result.evidence['action_admission']['capability_source_freshness'],bridge.admissions[0])
            self.assertRegex(result.evidence['command_sha256'],r'^[a-f0-9]{64}$')
            self.assertTrue(result.evidence['queue_request_id'])
        print('SYNTHETIC_TURNAROUND '+json.dumps({'mode':mode,'added_delay_seconds':delay,'native_admission':bridge.admissions[0]},sort_keys=True),flush=True)
        return bridge

    def test_full_actual_gateway_chain_admits_with_unchanged_tick_and_age_caps(self):
        bridge=self.run_case(0.,'success');sample=bridge.admissions[0]
        self.assertLessEqual(sample['tick_delta'],5)
        self.assertLessEqual(int(sample['elapsed_nanos']),800000000)
        self.assertTrue(any(p.startswith('/control/capability-snapshot?') for p in bridge.http_reads))

    def test_delayed_admission_fails_five_ticks_without_reclock_or_retry(self):
        bridge=self.run_case(.35,'reject');sample=bridge.admissions[0]
        self.assertTrue(sample['tick_delta_exceeded'])
        self.assertEqual(bridge.action['status'],'idle')
        self.assertEqual(bridge.selected,0)

    def test_long_admission_fails_original_800ms_without_retry(self):
        bridge=self.run_case(.85,'reject');sample=bridge.admissions[0]
        self.assertTrue(sample['nano_age_exceeded'])
        self.assertTrue(sample['tick_delta_exceeded'])
        self.assertEqual(bridge.action['status'],'idle')
        self.assertEqual(bridge.selected,0)


if __name__=='__main__':unittest.main()
