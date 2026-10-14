"""Synchronize embedded MCP schemas from pure Python contracts; no runtime imports."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

def expected(source):
    # --check must not create bytecode beside the canonical contracts.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('mdc_schema_contracts', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return 'export const toolboxSchemas=' + json.dumps(module.TOOL_SCHEMAS, separators=(',', ':')) + ';'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    target = folder / 'toolbox.mjs'
    lines = target.read_text().splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith('export const toolboxSchemas=')]
    if len(matches) != 1:
        raise ValueError('Expected exactly one embedded schema declaration')
    index = matches[0]
    wanted = expected(folder.parents[1] / 'capability-runtime/mdc_toolbox/contracts.py') + '\n'
    if args.check:
        if lines[index] != wanted:
            print('MCP/Python schema drift: run client-mod/mcp/sync-toolbox-schema.py', file=sys.stderr)
            return 1
        print('MCP/Python schemas match')
        return 0
    lines[index] = wanted
    target.write_text(''.join(lines))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
