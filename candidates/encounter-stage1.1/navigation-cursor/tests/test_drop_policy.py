import unittest
from navigation_cursor import DropPolicy, LocalTerrain, RouteCursor
from test_navigation_cursor import observation


def descent(height, *, health=20, food=20, saturation=4, supplies=True):
    start, end = (0,92,0),(1,92-height,0)
    o = observation(start, [start,end])
    p=o['state']['player']
    p.update(health=health,food=food,saturation=saturation,
             inventory=[{'id':'minecraft:bread','count':2}] if supplies else [])
    # Explicitly observed entire fall shaft, not inferred air from absent cells.
    sample = next(c for c in o['terrain']['cells'] if c['collision_empty'])
    cells={(c['x'],c['y'],c['z']):c for c in o['terrain']['cells']}
    for y in range(end[1],start[1]+2):
        cells[(1,y,0)]={**sample,'x':1,'y':y,'z':0,'collision_empty':True,'full_top_support':False}
    o['terrain']['cells']=list(cells.values())
    return o,start,end


class DropTests(unittest.TestCase):
    def test_observed_three_block_drop_is_direct_edge(self):
        o,a,b=descent(3)
        t=LocalTerrain(o)
        self.assertTrue(t.edge(a,b))
        self.assertEqual(t.graph(a,set())[b],a)

    def test_four_and_five_block_falls_allow_small_damage_with_health_margin(self):
        for height in (4,5):
            o,a,b=descent(height)
            self.assertTrue(LocalTerrain(o).edge(a,b))

    def test_hunger_or_no_supplies_increases_cost_without_rejecting_healthy_fall(self):
        baseline=DropPolicy().cost(4,descent(4)[0]['state']['player'])
        for changes in ({'food':17},{'saturation':0},{'food':12,'supplies':False}):
            o,a,b=descent(4,**changes)
            self.assertTrue(LocalTerrain(o).edge(a,b))
            self.assertGreater(DropPolicy().cost(4,o['state']['player']),baseline)

    def test_insufficient_current_health_blocks_fall_even_with_food(self):
        o,a,b=descent(4,health=3)
        self.assertFalse(LocalTerrain(o).edge(a,b))

    def test_unknown_cell_anywhere_in_shaft_blocks_drop(self):
        o,a,b=descent(4)
        o['terrain']['cells']=[c for c in o['terrain']['cells'] if (c['x'],c['y'],c['z'])!=(1,91,0)]
        self.assertFalse(LocalTerrain(o).edge(a,b))

    def test_obstacle_at_original_head_height_blocks_drop(self):
        o,a,b=descent(3)
        t=LocalTerrain(o)
        t.cells[(1,93,0)]['collision_empty']=False
        self.assertFalse(t.edge(a,b))

    def test_missing_floor_beyond_scan_boundary_is_not_assumed(self):
        o,a,b=descent(4)
        o['terrain']['cells']=[c for c in o['terrain']['cells'] if c['y']>=88]
        self.assertFalse(LocalTerrain(o).edge(a,b))

    def test_lava_and_hazardous_landing_block_fall(self):
        for change in ({'fluid':'minecraft:lava'},{'hazards':['damage']}):
            o,a,b=descent(3)
            t=LocalTerrain(o)
            t.cells[(1,88,0)].update(change)
            self.assertFalse(t.edge(a,b))

    def test_higher_and_diagonal_drop_not_admitted(self):
        o,a,b=descent(6)
        self.assertFalse(LocalTerrain(o).edge(a,b))
        o,a,b=descent(3)
        self.assertFalse(LocalTerrain(o).edge(a,(1,89,1)))

    def test_drop_slice_ends_at_landing(self):
        c=RouteCursor([(0,92,0),(1,89,0),(2,89,0)])
        self.assertEqual(len(c.slice(2)),1)
        self.assertFalse(c.slice(2)[0]['jump'])
        self.assertEqual(c.index,1)

    def test_opt_out_retains_v1_one_block_policy(self):
        o,a,b=descent(3)
        self.assertFalse(LocalTerrain(o,DropPolicy(max_blocks=1)).edge(a,b))

if __name__=='__main__':unittest.main()
