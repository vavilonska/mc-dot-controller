package io.github.campione01.mineclientbridge;

/** Pure exact callback-boundary identity. A late callback never owns its replacement. */
record PlacementOwnerFence(Object owner,Object player,Object level,Object gameMode,Object menu,Object screen,
                           String actionSession,String worldGeneration) {
    boolean same(Object owner,Object player,Object level,Object gameMode,Object menu,Object screen,
                 String actionSession,String worldGeneration) {
        return this.owner==owner && this.player==player && this.level==level && this.gameMode==gameMode
            && this.menu==menu && this.screen==screen && this.actionSession.equals(actionSession)
            && this.worldGeneration.equals(worldGeneration);
    }
}
