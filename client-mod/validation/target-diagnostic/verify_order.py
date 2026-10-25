from pathlib import Path
import json,hashlib,sys
from classfile import ClassFile,instructions
root=Path(sys.argv[1]);out=Path(sys.argv[2]);rows={};pins={}
def methods(name):
 p=root/(name+'.class');b=p.read_bytes();pins[str(p)]=hashlib.sha256(b).hexdigest();c=ClassFile(b);result={}
 for m in c.methods:
  if 'Code' not in m['attributes']:continue
  a=m['attributes']['Code'];n=int.from_bytes(a[4:8],'big');result[m['name']+m['descriptor']]=instructions(c,a[8:8+n])
 return result
def offset(insns,match):
 found=[r['offset'] for r in insns if match in r.get('reference','')];assert len(found)==1,(match,found);return found[0]
g=methods('net_minecraft_client_multiplayer_MultiPlayerGameMode');attack=g['attack(Lnet/minecraft/world/entity/player/Player;Lnet/minecraft/world/entity/Entity;)V']
order=[offset(attack,x) for x in ['ClientPacketListener.send:','mineclientBridge$combatLocalAttack:','Player.attack:','mineclientBridge$targetGameModeCooldown:','Player.resetAttackStrengthTicker:']];assert order==sorted(order);rows['game_mode_attack_offsets']=order
p=methods('net_minecraft_world_entity_player_Player');attack=p['attack(Lnet/minecraft/world/entity/Entity;)V'];order=[offset(attack,x) for x in ['mineclientBridge$targetMeleeSweep:','mineclientBridge$targetMeleeImpact:','world/entity/Entity.hurt:']];assert order==sorted(order);rows['primary_player_effect_offsets']=order
common=methods('net_minecraft_client_multiplayer_ClientCommonPacketListenerImpl');send=common['send(Lnet/minecraft/network/protocol/Packet;)V'];order=[offset(send,x) for x in ['NetworkRegistry.checkPacket:','mineclientBridge$placementSend:','Connection.send:']];assert order==sorted(order);rows['final_send_offsets']=order
for ms,name,expected in [(g,'mineclientBridge$combatLocalAttack','ScopedTargetDispatch.beforeAttack:'),(p,'mineclientBridge$targetMeleeImpact','ScopedTargetDispatch.beforeMeleeImpact:'),(common,'mineclientBridge$placementSend','ScopedTargetDispatch.send:')]:
 found=[ins for key,ins in ms.items() if name+"(" in key];assert len(found)==1;offset(found[0],expected)
result={'status':'passed','scope':'Retained actual TEST2.11 transformed bytecode; unchanged Mixin call sites. This is not execution of populated Minecraft or attribution of the live failure.','input_class_sha256':pins,'orders':rows};out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(rows))
