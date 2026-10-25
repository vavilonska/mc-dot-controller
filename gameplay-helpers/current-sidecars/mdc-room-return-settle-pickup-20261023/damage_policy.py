"""Explicit ordinary-bout risk budget. Not a native or mining guard change."""
import math

class DamagePolicy:
    def __init__(self,cfg,first):
        if not isinstance(cfg,dict) or set(cfg)!={'stop_health','max_observed_damage','fire_grace_seconds'}:
            raise ValueError('damage_policy_exact_fields_required')
        for key in cfg:
            value=cfg[key]
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('invalid_damage_policy_number')
        if not 0<cfg['stop_health']<=20 or not 0<cfg['max_observed_damage']<=20 or not 0<=cfg['fire_grace_seconds']<=2:
            raise ValueError('damage_policy_out_of_range')
        self.cfg=dict(cfg);self.previous=float(first['player']['health']);self.total=0.;self.fire_deadline=None;self.fire_attack_baseline=None
    def observe(self,s,now,attack_count=0):
        p=s['player'];hp=p['health']
        if type(hp) not in (int,float) or not math.isfinite(hp):return 'invalid_health'
        self.total+=max(0.,self.previous-hp);self.previous=hp
        if not p.get('alive') or hp<=0:return 'player_dead'
        if hp<=self.cfg['stop_health']:return 'damage_policy_stop_health'
        if self.total>=self.cfg['max_observed_damage']:return 'damage_policy_observed_damage_limit'
        for k in ('in_lava','in_water','eye_in_water','in_powder_snow'):
            if p.get(k):return k
        if p.get('on_fire') and self.fire_deadline is None:
            self.fire_deadline=now+self.cfg['fire_grace_seconds'];self.fire_attack_baseline=attack_count
        if self.fire_deadline is not None:
            if now>=self.fire_deadline:return 'damage_policy_fire_deadline'
            if attack_count>self.fire_attack_baseline:return 'damage_policy_fire_one_known_hit_complete'
        return None
    def snapshot(self):
        return dict(config=self.cfg,observed_damage=self.total,previous_health=self.previous,
                    fire_deadline=self.fire_deadline,fire_attack_baseline=self.fire_attack_baseline)
