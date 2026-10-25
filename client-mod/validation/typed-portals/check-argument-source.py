#!/usr/bin/env python3
"""Static placement guard: complements production-policy and real-argument tests."""
from pathlib import Path
import re
root=Path(__file__).resolve().parents[3]
java=root/'client-mod/src/main/java/io/github/campione01/mineclientbridge'
source=(java/'ScopedItemInteraction.java').read_text()
def body(name):
    match=re.search(r'^\s+(?:private )?(?:static )?(?:void|boolean|TypedBoundaryPolicy|PlacementPacketBinding) '+name+r'\(',source,re.MULTILINE); assert match,name
    start=source.index('{',match.start()); depth=1; end=start+1
    while depth:
        depth += (source[end]=='{')-(source[end]=='}'); end+=1
    return source[start+1:end-1]
checks=0
for name,latch in [('beforeUse','attempted=true'),('enterUse','useCount++'),('beforeItemUse','itemCalls++'),
                   ('beforeFlintEffect','localEffectCount++'),('itemResult','itemReturns++'),('packet','expectedPacket=wire')]:
    code=body(name); assert 'finalArguments(' in code and code.rindex('finalArguments(')<code.index(latch),name
    tail=code[code.index(latch):];assert not any(s in tail for s in ['check(','finalBinding(','ExternalControllerGuard','context(']),name;checks+=1
code=body('send')
for latch in ['selectionPackets++','packetCount++']:
    at=code.index(latch);assert code.rfind('finalArguments(',0,at)>=0;checks+=1
assert 'ItemInteractionArgumentFence' in body('finalArguments') or 'argumentFence.check(this::finalBinding,arguments)' in body('finalArguments');checks+=1
reader=(java/'TypedPortalReaders.java').read_text();assert 'getDeclaredField("hitResult")' in reader and 'trySetAccessible()' in reader and 'typed_item_context_raw_reader_unavailable' in reader;checks+=1
assert body('context').index('TypedPortalReaders.contextHit(c)')<body('context').index('c.getClickedPos()');checks+=1
assert 'TypedPortalReaderPolicy.exact(p,ServerboundUseItemOnPacket.class)' in body('packetIdentity');checks+=1
print(f'typed item final argument placement source checks: {checks} passed')
