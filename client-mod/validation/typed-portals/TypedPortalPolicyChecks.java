package io.github.campione01.mineclientbridge;
/** Offline tests exercise the exact production pure settlement/transition/reentrant-fence policies. */
public final class TypedPortalPolicyChecks {
    private static int checks;
    private static class MutatingComponent {int invoked;public boolean equals(Object other){invoked++;throw new AssertionError("component equals invoked");}public int hashCode(){invoked++;throw new AssertionError("component hash invoked");}}
    private static class PlainReader { int read(){return 1;} }
    private static class LateMutatingReader extends PlainReader { int calls;int read(){calls++;return 2;} }
    private static void check(boolean c){checks++;if(!c)throw new AssertionError("check "+checks);}
    private static void fails(Runnable r){try{r.run();throw new AssertionError("expected failure");}catch(IllegalStateException expected){checks++;}}
    public static void main(String[] args){
        // Exact production final-query fence at all eight item use/effect/packet seams.
        for(String seam:new String[]{"beforeUse","enterUse","beforeItemUse","beforeFlintEffect","itemResult","packet","selectionSend","useSend"}){
            var safe=new ItemInteractionArgumentFence();Object[] refs={new Object(),new Object()};long[] values={3,11};int[] queries={0},charges={0};
            safe.check(()->queries[0]++,()->new TypedBoundaryPolicy(refs,values));charges[0]++;
            check(queries[0]==1&&charges[0]==1);
            for(int changed=0;changed<4;changed++){
                var guarded=new ItemInteractionArgumentFence();Object[] ids={new Object(),new Object()};long[] numbers={3,11};int[] localQueries={0},localCharges={0};int mutation=changed;
                fails(()->{guarded.check(()->{localQueries[0]++;if(mutation<2)ids[mutation]=new Object();else numbers[mutation-2]++;},
                    ()->new TypedBoundaryPolicy(ids,numbers));localCharges[0]++;});
                check(localQueries[0]==1&&localCharges[0]==0); // Argument/sequence/slot changed, world owner did not.
                fails(()->guarded.check(()->localQueries[0]++,()->new TypedBoundaryPolicy(ids,numbers)));
                check(localQueries[0]==1&&localCharges[0]==0); // Poison prevents a query or a retry after uncertainty.
            }
        }
        var argumentReentry=new ItemInteractionArgumentFence();
        fails(()->argumentReentry.check(()->{try{argumentReentry.check(()->{},()->new TypedBoundaryPolicy(new Object[0],new long[0]));}catch(IllegalStateException ignored){}},
            ()->new TypedBoundaryPolicy(new Object[0],new long[0])));
        var nullArguments=new ItemInteractionArgumentFence();int[] neverQuery={0};
        fails(()->nullArguments.check(()->neverQuery[0]++,()->null));check(neverQuery[0]==0);

        for(int mutation=0;mutation<4;mutation++){
            Object[] identities={new Object(),new Object()};long[] facts={Double.doubleToLongBits(.5),1};
            var beforeQuery=new TypedBoundaryPolicy(identities,facts);var finalFence=new PlacementCallbackFence(()->true,()->1,()->1);int selectedMutation=mutation;
            fails(()->finalFence.check(()->{
                // Last external reader changes block identity, pose, or inventory count but leaves owner valid.
                if(selectedMutation==0)identities[0]=new Object();else if(selectedMutation==3)identities[1]=new Object();else facts[selectedMutation-1]++;
                if(!beforeQuery.same(new TypedBoundaryPolicy(identities,facts)))throw new IllegalStateException("raw boundary changed");
            }));
        }
        var component=new MutatingComponent();var key=new MutatingComponent();var originalComponents=new IdentityComponentSnapshot();originalComponents.add(key,component);
        var exactComponents=new IdentityComponentSnapshot();exactComponents.add(key,component);check(originalComponents.same(exactComponents,null));
        var replacementComponents=new IdentityComponentSnapshot();replacementComponents.add(key,new MutatingComponent());check(!originalComponents.same(replacementComponents,null));
        check(component.invoked==0&&key.invoked==0);
        Object damageType=new Object();var plainEyePatch=new IdentityComponentSnapshot();var eyeWithDamageZero=new IdentityComponentSnapshot();eyeWithDamageZero.add(damageType,Integer.valueOf(0));
        check(!plainEyePatch.same(eyeWithDamageZero,null)); // Eye must not borrow flint DAMAGE normalization.
        check(plainEyePatch.same(eyeWithDamageZero,damageType)); // Only flint opts into normalization.
        var malicious=new LateMutatingReader();
        fails(()->TypedPortalReaderPolicy.exact(malicious,PlainReader.class).read());check(malicious.calls==0);
        fails(()->TypedPortalReaderPolicy.exact(null,PlainReader.class));check(TypedPortalReaderPolicy.exact(new PlainReader(),PlainReader.class).read()==1);
        var s=new ItemInteractionSettlementPolicy(32767);
        check(s.permits(32767,false,0,0,false));check(!s.permits(0,false,1,1,true));
        check(s.permits(32767,true,1,1,false));check(!s.permits(0,true,1,1,false));
        check(!s.permits(32767,true,1,0,true));check(s.permits(0,true,1,1,true));
        s.commit(0,true);check(!s.permits(0,true,1,1,false));check(!s.permits(1,true,1,1,true));check(s.permits(0,true,1,1,true));
        fails(()->s.commit(1,true));
        var b=new PortalTransitionPolicy.Bound("a","s","p","server","world","minecraft:overworld","minecraft:the_nether",7,100,1000);
        var source=new PortalTransitionPolicy.Live("a","s","p","server","world","minecraft:overworld",7,900);
        var dest=new PortalTransitionPolicy.Live("a","s","p","server","new-world","minecraft:the_nether",7,900);
        check(PortalTransitionPolicy.permits(b,source,"world_transition",true,true,false,true));
        check(PortalTransitionPolicy.permits(b,dest,"capability_world_changed",true,true,false,true));
        check(!PortalTransitionPolicy.permits(b,source,"world_transition",true,true,false,false));
        check(!PortalTransitionPolicy.permits(b,dest,"world_transition",true,true,false,false));
        check(PortalContactPolicy.permits(b,source,true,true,true,true,true,true,true,true,false));
        check(PortalContactPolicy.originalHealth(false,20,20)); // Dimension removal alone is not death.
        check(!PortalContactPolicy.originalHealth(true,20,20));
        check(!PortalContactPolicy.originalHealth(false,0,20));
        check(!PortalContactPolicy.originalHealth(false,Float.NaN,20));
        check(!PortalContactPolicy.originalHealth(false,19,20));
        check(PortalTransitionPolicy.permits(b,source,"player_changed",true,true,false,
            PortalContactPolicy.originalHealth(false,20,20)&&PortalContactPolicy.sourceLifecycle(true,true,true,true,10,11)));
        check(!PortalTransitionPolicy.permits(b,source,"player_changed",true,true,false,
            PortalContactPolicy.originalHealth(true,0,20)&&PortalContactPolicy.sourceLifecycle(true,false,false,true,10,11)));
        check(!PortalTransitionPolicy.permits(b,source,"player_changed",true,true,false,
            PortalContactPolicy.originalHealth(false,20,20)&&PortalContactPolicy.sourceLifecycle(false,true,true,true,10,11)));
        check(!PortalTransitionPolicy.permits(b,dest,"player_changed",true,true,false,PortalContactPolicy.originalHealth(true,0,20)));
        check(PortalContactPolicy.sourceLifecycle(true,true,true,true,10,11));
        check(!PortalContactPolicy.sourceLifecycle(true,false,true,true,10,11));
        check(!PortalContactPolicy.sourceLifecycle(false,true,true,true,10,11));
        check(!PortalContactPolicy.sourceLifecycle(true,true,false,true,10,11));
        check(!PortalContactPolicy.sourceLifecycle(true,true,true,true,10,12));
        check(PortalContactPolicy.overlaps(false,1,64,0,.9,64,.2,1.5,65.8,.8));
        check(!PortalContactPolicy.overlaps(false,1,64,0,.2,64,.2,.8,65.8,.8));
        check(PortalContactPolicy.overlaps(true,1,64,0,.9,64,.2,1.5,65.8,.8));
        check(!PortalContactPolicy.overlaps(true,1,64,0,.9,65,.2,1.5,66.8,.8));
        for(int missing=0;missing<8;missing++){
            boolean[] yes={true,true,true,true,true,true,true,true};yes[missing]=false;
            check(!PortalContactPolicy.permits(b,source,yes[0],yes[1],yes[2],yes[3],yes[4],yes[5],yes[6],yes[7],false));
        }
        check(!PortalContactPolicy.permits(b,source,true,true,true,true,true,true,true,true,true));
        check(!PortalContactPolicy.permits(b,dest,true,true,true,true,true,true,true,true,false));
        for(var v:new PortalTransitionPolicy.Live[]{
            new PortalTransitionPolicy.Live("replacement","s","p","server","world","minecraft:overworld",7,900),
            new PortalTransitionPolicy.Live("a","new-session","p","server","world","minecraft:overworld",7,900),
            new PortalTransitionPolicy.Live("a","s","foreign-player","server","world","minecraft:overworld",7,900),
            new PortalTransitionPolicy.Live("a","s","p","disconnected","world","minecraft:overworld",7,900),
            new PortalTransitionPolicy.Live("a","s","p","server","replacement","minecraft:overworld",7,900),
            new PortalTransitionPolicy.Live("a","s","p","server","world","minecraft:overworld",8,900),
            new PortalTransitionPolicy.Live("a","s","p","server","world","minecraft:overworld",7,1000)})
            check(!PortalContactPolicy.permits(b,v,true,true,true,true,true,true,true,true,false));
        for(String reason:new String[]{"cancel_requested","timeout","player_dead","lost_focus"})check(!PortalTransitionPolicy.permits(b,dest,reason,true,true,false,true));
        check(!PortalTransitionPolicy.permits(b,dest,"world_transition",false,true,false,true));
        check(!PortalTransitionPolicy.permits(b,dest,"world_transition",true,false,false,true));
        check(!PortalTransitionPolicy.permits(b,dest,"world_transition",true,true,true,true));
        for(var bad:new PortalTransitionPolicy.Live[]{
            new PortalTransitionPolicy.Live("other","s","p","server","new-world","minecraft:the_nether",7,900),
            new PortalTransitionPolicy.Live("a","other","p","server","new-world","minecraft:the_nether",7,900),
            new PortalTransitionPolicy.Live("a","s","other","server","new-world","minecraft:the_nether",7,900),
            new PortalTransitionPolicy.Live("a","s","p","other","new-world","minecraft:the_nether",7,900),
            new PortalTransitionPolicy.Live("a","s","p","server","world","minecraft:the_nether",7,900),
            new PortalTransitionPolicy.Live("a","s","p","server","new-world","minecraft:the_end",7,900),
            new PortalTransitionPolicy.Live("a","s","p","server","new-world","minecraft:the_nether",8,900),
            new PortalTransitionPolicy.Live("a","s","p","server","new-world","minecraft:the_nether",7,1000),
            new PortalTransitionPolicy.Live("a","s","p","server","new-world","minecraft:the_nether",7,99)})
            check(!PortalTransitionPolicy.permits(b,bad,"world_transition",true,true,false,true));
        long[] clock={1},tick={1};boolean[] owner={true};var fence=new PlacementCallbackFence(()->owner[0],()->clock[0],()->tick[0]);
        fence.check(()->{});fails(()->fence.check(()->owner[0]=false));owner[0]=true;fails(()->fence.check(()->{}));
        var reentrant=new PlacementCallbackFence(()->true,()->1,()->1);fails(()->reentrant.check(()->{try{reentrant.check(()->{});}catch(IllegalStateException ignored){}}));
        var delayed=new PlacementCallbackFence(()->true,()->clock[0],()->1);fails(()->delayed.check(()->clock[0]+=250000001));
        var moved=new PlacementCallbackFence(()->true,()->1,()->tick[0]);fails(()->moved.check(()->tick[0]++));
        System.out.println("typed portal production policy checks: "+checks+" passed");
    }
}
