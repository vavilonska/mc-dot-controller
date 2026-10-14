package io.github.campione01.mineclientbridge;
/** Exact final-send primitive identity comparisons execute production record equality. */
public final class PlacementPacketChecks {
    public static void main(String[] args){
        var expected=new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"UP",1.5,65,2.5,false,"BLOCK");int checks=0;
        for(var actual:new PlacementPacketBinding[]{
            new PlacementPacketBinding(5,"MAIN_HAND",1,64,2,"UP",1.5,65,2.5,false,"BLOCK"),
            new PlacementPacketBinding(4,"OFF_HAND",1,64,2,"UP",1.5,65,2.5,false,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",2,64,2,"UP",1.5,65,2.5,false,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",1,65,2,"UP",1.5,65,2.5,false,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",1,64,3,"UP",1.5,65,2.5,false,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"DOWN",1.5,65,2.5,false,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"UP",1.5001,65,2.5,false,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"UP",1.5,65.0001,2.5,false,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"UP",1.5,65,2.5001,false,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"UP",1.5,65,2.5,true,"BLOCK"),
            new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"UP",1.5,65,2.5,false,"MISS")}){
            if(expected.equals(actual))throw new AssertionError("changed binding accepted");checks++;
        }
        for(double n:new double[]{Double.NaN,Double.POSITIVE_INFINITY,Double.NEGATIVE_INFINITY}){
            try{new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"UP",n,65,2.5,false,"BLOCK");throw new AssertionError("nonfinite accepted");}catch(IllegalArgumentException good){checks++;}
        }
        if(!expected.equals(new PlacementPacketBinding(4,"MAIN_HAND",1,64,2,"UP",1.5,65,2.5,false,"BLOCK")))throw new AssertionError();checks++;
        System.out.println("PASS production placement final packet identity: "+checks);
    }
}
