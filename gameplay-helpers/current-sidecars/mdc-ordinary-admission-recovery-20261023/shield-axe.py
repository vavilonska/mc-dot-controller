#!/usr/bin/env python3
"""Explicit short stationary Blaze shield/axe bout, followed by the verified retreat."""
import argparse,datetime,json,math,time
from pathlib import Path
import idle_guard as idle

def target(s,uid):
    return next((e for e in s.get('nearby',{}).get('entities',[]) if e.get('uuid')==uid and e.get('type')=='minecraft:blaze' and e.get('alive') is not False and idle.position_ok(e)),None)
def equipped(s):
    return s['player'].get('mainhand',{}).get('id','').endswith('_axe') and s['player'].get('offhand',{}).get('id')=='minecraft:shield'
def ready_hit(s,uid):
    h=s.get('crosshair',{});p=s['player'];reach=p.get('entity_interaction_range',0);strength=p.get('attack_strength',0)
    return (h.get('type')=='entity' and h.get('uuid')==uid and h.get('entity_type')=='minecraft:blaze'
        and idle.position_ok(h.get('location')) and idle.position_ok(p.get('eye_position'))
        and type(reach) in (float,int) and math.isfinite(reach) and type(strength) in (float,int)
        and math.isfinite(strength) and strength>=.95 and idle.distance(p['eye_position'],h['location'])<=min(3.,reach))

class Fight:
    def __init__(self,c,cfg,s,now):
        self.c=c;self.cfg=cfg;self.escape=idle.Watch(c,cfg,s)
        duration=cfg.get('max_seconds',15)
        if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=15:raise idle.Refused('max_seconds_must_be_0_to_15')
        explicit=cfg.get('target_uuid');mode=cfg.get('target_mode')
        if not (isinstance(explicit,str) and explicit) and mode!='closest_blaze_within_3m':raise idle.Refused('explicit_blaze_target_required')
        candidates=[e for e in s.get('nearby',{}).get('entities',[]) if e.get('type')=='minecraft:blaze' and idle.position_ok(e) and e.get('alive') is not False and idle.distance(s['player'],e)<=3]
        self.uid=explicit if explicit else min(candidates,key=lambda e:idle.distance(s['player'],e))['uuid'] if candidates else None
        self.phase='TRACK';self.reason='short_stationary_bout';self.deadline=now+duration
        self.previous_health=idle.health(s);self.shield_owned=False;self.release_sent=False;self.attack_attempts=0
        self.cooldown_wait=False;self.uncertain=False;self.done=False
        self.c.note('combat_armed',target_uuid=self.uid,deadline_seconds=duration,route=cfg['waypoints'],allow_presence_risk=cfg.get('allow_presence_risk') is True)
    def needs(self,why):
        self.phase='NEEDS_OPERATOR';self.reason=why;self.c.note('combat_needs_operator',reason=why)
    def send(self,path,body):
        try:
            code,o=self.c.request('POST',path,body)
            if code==200 and o.get('ok') is True:return True
        except Exception:pass
        self.uncertain=True;self.needs('ordinary_input_response_unresolved_read_only_no_reissue');return False
    def shield(self):
        # Mark attempted before transmission; an unresolved down is never reissued.
        self.escape.shield_attempted=True
        if self.send('/control/key',dict(mapping='key.use',action='down')):
            self.shield_owned=True;self.release_sent=False;return True
        return False
    def release(self):
        if self.release_sent:return True
        self.release_sent=True
        if self.send('/control/key',dict(mapping='key.use',action='up')):
            self.shield_owned=False;return True
        return False
    def hazard(self,s,now):
        if now>=self.deadline:return 'bout_deadline_retreat'
        if not equipped(s):return 'actual_axe_or_shield_unavailable'
        if idle.health(s)<self.previous_health:return 'health_decreased'
        for k in ('on_fire','in_lava','in_water','eye_in_water','in_powder_snow'):
            if s['player'].get(k):return k
        for e in idle.threats(s,self.cfg):
            los=e.get('line_of_sight')
            threat=e['distance']<=12 if e['projectile'] else (
                los is not False and e['distance']<=3)
            if e.get('uuid')!=self.uid and threat and self.cfg.get('allow_presence_risk') is not True:return 'additional_near_threat'
        e=target(s,self.uid)
        if not e:return 'locked_target_unavailable_no_chase'
        # A living observed target outside reach is watched from here; ready_hit still gates every click.
        return None
    def begin_retreat(self,why):
        self.phase='RETREAT_RELEASE';self.reason=why
    def step(self,s,now,disarm=False,stop_fight=False):
        same=idle.context(s)==self.cfg['expected_context'];valid=idle.valid_world(s) and s['player'].get('alive') and idle.health(s)>0
        if self.phase=='RETREATING':
            summary=self.escape.step(s,disarm);self.done=self.escape.done
            return dict(summary,combat_phase=self.phase,combat_target_uuid=self.uid,known_attack_clicks=self.attack_attempts)
        if disarm:
            # Explicit operator handoff only; not a normal combat completion in the open.
            if idle.active(s):
                self.needs('foreign_action_no_takeover_during_disarm');return self.summary(s)
            self.escape.disarm(s);self.done=self.escape.done
            return dict(self.escape.summary(s),combat_phase=self.phase,combat_target_uuid=self.uid,known_attack_clicks=self.attack_attempts)
        if not same or not valid:
            self.needs('context_or_world_changed_no_new_input');return self.summary(s)
        if idle.active(s):
            self.needs('foreign_action_no_takeover');return self.summary(s)
        if self.phase=='NEEDS_OPERATOR':return self.summary(s)
        # Idle ownership was checked at arm. During fighting only our shield may be held.
        keys=set(s.get('held_inputs',{}).get('keys',[]))
        if keys-{'key.use'}:
            self.needs('unexpected_held_input_no_takeover');return self.summary(s)
        why=self.hazard(s,now)
        if stop_fight:why='operator_stop_fight_retreat'
        if why and self.phase!='RETREAT_RELEASE':self.begin_retreat(why)
        self.previous_health=idle.health(s)
        if self.phase=='RETREAT_RELEASE':
            if self.shield_owned or s['player'].get('using_item') or not idle.neutral(s):
                self.release();return self.summary(s)
            self.escape.shield_attempted=False;self.escape.shield_release_sent=False
            self.escape.start_retreat(s,self.reason);self.phase='RETREATING'
            return dict(self.escape.summary(s),combat_phase=self.phase,combat_target_uuid=self.uid,known_attack_clicks=self.attack_attempts)
        e=target(s,self.uid)
        if self.cooldown_wait:
            if s['player'].get('attack_strength',1)<.95:self.cooldown_wait=False
            else:return self.summary(s)
        if not self.shield_owned and self.phase!='STRIKE_CHECK':
            self.shield();return self.summary(s)
        if self.phase=='TRACK':
            if self.send('/control/look',idle.aim(s,e)):self.phase='AIM_CHECK'
        elif self.phase=='AIM_CHECK':
            if ready_hit(s,self.uid):
                if self.release():self.phase='STRIKE_CHECK'
            else:self.phase='TRACK'
        elif self.phase=='STRIKE_CHECK':
            if s['player'].get('using_item') or not idle.neutral(s):return self.summary(s)
            if not ready_hit(s,self.uid):
                if self.shield():self.phase='TRACK'
            elif self.send('/control/key',dict(mapping='key.attack',action='click')):
                self.attack_attempts+=1;self.cooldown_wait=True
                # Known click is followed immediately by shield down, not a model/UI pause.
                if self.shield():self.phase='TRACK'
        return self.summary(s)
    def summary(self,s):
        return dict(phase=self.phase,reason=self.reason,exclusive_owner_until_disarmed=not self.done,
            combat_target_uuid=self.uid,known_attack_clicks=self.attack_attempts,input_response_uncertain=self.uncertain,
            allow_presence_risk=self.cfg.get('allow_presence_risk') is True,
            observed_projectiles=[dict(uuid=e.get('uuid'),type=e.get('type'),distance=e['distance'],line_of_sight=e.get('line_of_sight'))
                for e in idle.threats(s,self.cfg) if e['projectile']],
            health=idle.health(s),pose=idle.point(s['player']),on_fire=s['player'].get('on_fire'),
            blocking=s['player'].get('blocking'),using_item=s['player'].get('using_item'),neutral=idle.neutral(s),active=s['client_action'],
            additional_hostiles_observed=[dict(uuid=e.get('uuid'),distance=e['distance'],line_of_sight=e.get('line_of_sight'))
                for e in idle.threats(s,self.cfg) if e.get('uuid')!=self.uid and not e['projectile'] and e['distance']<=8])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());a.run_dir.mkdir(parents=True,exist_ok=False,mode=0o700);c=idle.Client(a.run_dir)
    c.note('config',config=cfg)
    try:f=Fight(c,cfg,c.state(),time.monotonic())
    except Exception as e:
        r=dict(phase='REFUSED_NO_INPUT',reason=str(e) if isinstance(e,idle.Refused) else type(e).__name__)
        (a.run_dir/'RESULT.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r));return 2
    while not f.done:
        try:
            s=c.state();r=f.step(s,time.monotonic(),(a.run_dir/'DISARM').exists(),(a.run_dir/'STOP_FIGHT').exists())
            r['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();c.note('observation',**r)
        except Exception as e:
            # No fresh state => no new input. An input uncertainty is never turned into replay.
            r=dict(phase='OBSERVATION_UNAVAILABLE',reason=type(e).__name__,exclusive_owner_until_disarmed=True)
            c.note('observation_gap_no_new_input',**r)
        tmp=a.run_dir/'STATUS.tmp';tmp.write_text(json.dumps(r,indent=2)+'\n');tmp.replace(a.run_dir/'STATUS.json');time.sleep(.1)
    (a.run_dir/'RESULT.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
if __name__=='__main__':raise SystemExit(main())
