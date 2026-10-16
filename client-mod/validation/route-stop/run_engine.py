"""Fresh production controller regression with explicit synthetic engine readers."""
from pathlib import Path
import argparse
import json
import os
import sys
from runner_common import new_output, run, sha256

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
p.add_argument('--output', type=Path, required=True)
p.add_argument('--java', required=True)
p.add_argument('--javac', required=True)
p.add_argument('--gson', type=Path, required=True)
a = p.parse_args()
here = Path(__file__).resolve().parent
repo = a.repo.resolve()
native = repo / 'client-mod/src/main/java/io/github/campione01/mineclientbridge'
out = new_output(a.output, repo)
src, classes = out / 'synthetic-src', out / 'classes'
classes.mkdir()
gson = str(a.gson.resolve())
run(out, 'prepare', [sys.executable, '-B', str(here / 'prepare_engine.py'), str(src), '--repo', str(repo)])


def extract(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


source = (native / 'ClientActions.java').read_text()
signatures = ['static boolean ownsScopedLocalSegment(', 'static String session()',
              'static boolean ownsInput()', 'static long ownershipRevision()', 'static void localSegmentMotionFailed(']
snippets = [extract(source, signature) for signature in signatures]
post_catch=extract(extract(source,'private static void postTick()'),'catch (RuntimeException failure)')
post_branch=post_catch[post_catch.index('{')+1:-1]
(src / 'io/github/campione01/mineclientbridge/ClientActions.java').write_text('''package io.github.campione01.mineclientbridge;
final class ClientActions {static ActionRegistry ACTIONS=new ActionRegistry();static RuntimeAction active;static long ownershipRevision;static boolean released=true;
 static final class RuntimeAction{ActionRegistry.Entry entry;ScopedLocalSegmentMovement scopedLocalSegment;ScopedPlacement scopedPlacement;RuntimeAction(ActionRegistry.Entry e,ScopedLocalSegmentMovement m){entry=e;scopedLocalSegment=m;}}
 static void finish(String status,String reason){active=null;ACTIONS.finishAfterCleanup(status,reason,released);}
 static void failException(RuntimeException failure){finish("failed","client_action_error");}
 static void reset(){ACTIONS=new ActionRegistry();active=null;ownershipRevision=0;released=true;}
 static ActionRegistry.Entry install(ClientActionRequest r,ScopedLocalSegmentMovement m){var e=ACTIONS.begin(r);active=new RuntimeAction(e,m);ownershipRevision++;return e;}
 static void end(boolean released){active=null;ACTIONS.finishAfterCleanup("cancelled","fixture_end",released);}
''' + '\n'.join(snippets) + '\nstatic void postTickFailure(RuntimeAction entered,RuntimeException failure){'+post_branch+'}\n}')
# These production files are compiled unchanged; only engine readers and
# unrelated ClientActions lifecycle plumbing are synthetic.
names = ['ScopedLocalSegmentDispatch', 'ScopedLocalSegmentMovement', 'RouteTerrainDiagnostics', 'ScopedLocalSegmentPolicy', 'ScopedFlatPolicy', 'ScopedMovementEntities',
         'ScopedEntityPolicy', 'RouteThreatDiagnostics', 'ScopedRouteThreatPolicy', 'ScopedRouteThreatEntities', 'ScopedRouteStopPolicy', 'ScopedRouteStopEntities', 'RouteEntityDiagnostics', 'RouteBeeDiagnostics', 'NativeLivingSnapshot', 'NativeBeeRouteObservation', 'ScopedRouteBeePolicy', 'ActionRegistry', 'ClientActionRequest', 'BridgeJson']
argv = [a.javac, '-J-Xmx384m', '-J-XX:ActiveProcessorCount=1', '-proc:none', '--release', '21',
        '-cp', gson, '-d', str(classes), *map(str, sorted(src.rglob('*.java'))),
        *[str(native / (name + '.java')) for name in names], str(here.parent / 'local-segment/LocalSegmentEngineChecks.java'), str(here.parent / 'spatial-threat/SpatialThreatEngineChecks.java'), str(here / 'RouteStopEngineChecks.java'), str(here / 'TerrainEquivalenceEngineChecks.java'), str(here / 'BeeRouteEngineChecks.java'), str(here / 'BeeDiagnosticEngineChecks.java'), str(here / 'BeeBatchEquivalenceEngineChecks.java')]
run(out, 'compile', argv)
run(out, 'engine', [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true',
                    '-cp', str(classes) + os.pathsep + gson,
                    'io.github.campione01.mineclientbridge.LocalSegmentEngineChecks', str(out)])
run(out, 'spatial-engine', [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true', '-cp', str(classes) + os.pathsep + gson, 'io.github.campione01.mineclientbridge.SpatialThreatEngineChecks', str(out)])
run(out, 'route-stop-engine', [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true', '-cp', str(classes) + os.pathsep + gson, 'io.github.campione01.mineclientbridge.RouteStopEngineChecks', str(out)])
run(out, 'terrain-equivalence-engine', [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true', '-cp', str(classes) + os.pathsep + gson, 'io.github.campione01.mineclientbridge.TerrainEquivalenceEngineChecks', str(out)])
run(out, 'route-bee-engine', [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true', '-cp', str(classes) + os.pathsep + gson, 'io.github.campione01.mineclientbridge.BeeRouteEngineChecks', str(out)])
run(out, 'bee-diagnostic-engine', [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true', '-cp', str(classes) + os.pathsep + gson, 'io.github.campione01.mineclientbridge.BeeDiagnosticEngineChecks', str(out)])
run(out, 'bee-batch-equivalence-engine', [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true', '-cp', str(classes) + os.pathsep + gson, 'io.github.campione01.mineclientbridge.BeeBatchEquivalenceEngineChecks', str(out)])
(out / 'source-sha256.json').write_text(json.dumps({name: sha256(native / (name + '.java')) for name in names}, indent=2))
(out / 'owner-source-binding.json').write_text(json.dumps({
    'ClientActions.java': sha256(native / 'ClientActions.java'),
    'NativeLivingObservation.java': sha256(native / 'NativeLivingObservation.java'),
    'query_signatures': signatures, 'extracted_post_tick_catch': post_catch, 'gson_sha256': sha256(a.gson),
    'harness_sha256': {path.name: sha256(path) for path in sorted(here.iterdir()) if path.is_file()},
    'scope': 'Unchanged production owner queries, motion-failure method and complete postTick catch body; remaining lifecycle scaffolding and engine readers are synthetic.'}, indent=2))
