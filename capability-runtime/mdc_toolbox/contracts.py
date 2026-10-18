"""Closed, versioned data contracts. Validation never grants execution authority."""
from __future__ import annotations
from copy import deepcopy
import json
import math
import re

API_VERSION = 'mdc.toolbox/1'
MAX_JSON_BYTES = 4 * 1024 * 1024
STATES = ('accepted', 'running', 'stopping', 'succeeded', 'blocked', 'failed', 'cancelled', 'interrupted', 'unknown')
EFFECT_CERTAINTIES = ('none_proven', 'known', 'unknown')
CLEANUP_CERTAINTIES = ('not_needed', 'pending', 'confirmed', 'unknown')
TERMINAL = frozenset(STATES) - {'accepted', 'running', 'stopping'}
PROFILES = ('player', 'inventory', 'menu', 'entities', 'local_terrain', 'survey', 'memory', 'compact', 'reconciliation')

class ToolboxError(ValueError):
    def __init__(self, code, reason, *, stage='validation', effect_certainty='none_proven', affected_ids=(), suggested_next_operation=None):
        super().__init__(reason)
        self.code, self.reason = code, reason
        self.stage, self.effect_certainty = stage, effect_certainty
        self.affected_ids, self.suggested_next_operation = list(affected_ids), suggested_next_operation
    def as_dict(self):
        return {'code': self.code, 'stage': self.stage, 'reason': self.reason, 'effect_certainty': self.effect_certainty,
                'affected_ids': self.affected_ids, 'suggested_next_operation': self.suggested_next_operation}


def json_data(value):
    """Reject non-JSON objects, non-finite values and recursive/oversized inputs."""
    nodes = [0]
    def visit(v, depth):
        nodes[0] += 1
        if depth > 32 or nodes[0] > 100000:
            raise ToolboxError('invalid_request', 'JSON structural limit exceeded')
        if v is None or type(v) in (str, bool, int):
            return
        if type(v) is float and math.isfinite(v):
            return
        if type(v) is dict:
            if not all(type(k) is str for k in v):
                raise ToolboxError('invalid_request', 'JSON keys must be strings')
            for child in v.values(): visit(child, depth + 1)
            return
        if type(v) is list:
            for child in v: visit(child, depth + 1)
            return
        raise ToolboxError('invalid_request', 'Only finite JSON data is accepted')
    try:
        visit(value, 0)
        data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, RecursionError, UnicodeError) as exc:
        if isinstance(exc, ToolboxError): raise
        raise ToolboxError('invalid_request', 'Invalid JSON encoding') from exc
    if len(data) > MAX_JSON_BYTES:
        raise ToolboxError('invalid_request', 'JSON byte limit exceeded')
    return data


def validate_schema(value, schema, path='$'):
    """Dependency-free validator for the closed toolbox schema vocabulary.

    Schemas are trusted package data, never supplied by the playing AI. Unknown
    schema keywords fail closed so a future plugin cannot silently weaken checks.
    """
    if path == '$': json_data(value)
    if schema is True: return value
    if schema is False: raise ToolboxError('invalid_request', f'{path}: value prohibited')
    allowed = {'type','properties','required','additionalProperties','patternProperties','propertyNames',
               'minProperties','maxProperties','items','minItems','maxItems','uniqueItems','enum','const',
               'minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf','minLength','maxLength',
               'pattern','oneOf','anyOf','allOf','not','if','then','else','description','title','default',
               '$schema','$id','$comment','examples','deprecated','readOnly','writeOnly','format'}
    unknown = set(schema) - allowed
    if unknown: raise ToolboxError('schema_unsupported', f'{path}: unsupported schema keywords {sorted(unknown)}')
    def bad(reason): raise ToolboxError('invalid_request', f'{path}: {reason}')
    def matches(sub):
        try: validate_schema(value, sub, path); return True
        except ToolboxError as exc:
            if exc.code != 'invalid_request': raise
            return False
    if 'allOf' in schema:
        for sub in schema['allOf']: validate_schema(value, sub, path)
    if 'oneOf' in schema and sum(matches(sub) for sub in schema['oneOf']) != 1: bad('expected exactly one schema alternative')
    if 'anyOf' in schema and not any(matches(sub) for sub in schema['anyOf']): bad('no schema alternative matched')
    if 'not' in schema and matches(schema['not']): bad('prohibited schema matched')
    if 'if' in schema:
        selected = schema.get('then' if matches(schema['if']) else 'else')
        if selected is not None: validate_schema(value, selected, path)
    if 'const' in schema and (value != schema['const'] or type(value) is not type(schema['const'])): bad('unexpected constant')
    if 'enum' in schema and not any(value == item and type(value) is type(item) for item in schema['enum']): bad('not an allowed value')
    types = {'object': lambda v: type(v) is dict, 'array': lambda v: type(v) is list,
             'string': lambda v: type(v) is str, 'integer': lambda v: type(v) is int,
             'number': lambda v: type(v) in (int,float) and not isinstance(v,bool),
             'boolean': lambda v: type(v) is bool, 'null': lambda v: v is None}
    if 'type' in schema:
        expected = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if any(t not in types for t in expected): raise ToolboxError('schema_unsupported', f'{path}: unknown type')
        if not any(types[t](value) for t in expected): bad('wrong JSON type')
    if type(value) is dict:
        props, patterns = schema.get('properties', {}), schema.get('patternProperties', {})
        if any(key not in value for key in schema.get('required', ())): bad('missing required fields')
        if len(value) < schema.get('minProperties', 0) or len(value) > schema.get('maxProperties', 100000): bad('object size outside bounds')
        for key, item in value.items():
            if 'propertyNames' in schema: validate_schema(key, schema['propertyNames'], f'{path}.<key>')
            covered = False
            if key in props:
                validate_schema(item, props[key], f'{path}.{key}'); covered = True
            for pattern, sub in patterns.items():
                if re.search(pattern, key): validate_schema(item, sub, f'{path}.{key}'); covered = True
            if not covered:
                extra = schema.get('additionalProperties', True)
                if extra is False: bad(f'unknown field {key}')
                if isinstance(extra, dict): validate_schema(item, extra, f'{path}.{key}')
    if type(value) is list:
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', 100000): bad('array size outside bounds')
        if schema.get('uniqueItems') and len({json_data(item) for item in value}) != len(value): bad('duplicate array values')
        for i, item in enumerate(value):
            if 'items' in schema: validate_schema(item, schema['items'], f'{path}[{i}]')
    if type(value) is str:
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', MAX_JSON_BYTES): bad('string length outside bounds')
        if 'pattern' in schema and re.search(schema['pattern'], value) is None: bad('string pattern mismatch')
    if type(value) in (int,float):
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf): bad('number outside bounds')
        if value <= schema.get('exclusiveMinimum', -math.inf) or value >= schema.get('exclusiveMaximum', math.inf): bad('number outside exclusive bounds')
        if 'multipleOf' in schema and not math.isclose(value / schema['multipleOf'], round(value / schema['multipleOf']), rel_tol=0, abs_tol=1e-9): bad('number not a multiple')
    return value


def obj(properties=None, required=()):
    return {'type':'object', 'properties':properties or {}, 'required':list(required), 'additionalProperties':False}
def integer(low, high): return {'type':'integer','minimum':low,'maximum':high}
def string(limit=128): return {'type':'string','minLength':1,'maxLength':limit}
IDENTIFIER = {'type':'string','pattern':'^[A-Za-z0-9_-]{1,80}$','maxLength':80}
REFERENCE = string(256)
VERSION = {'type':'string','const':API_VERSION}
CAPABILITY = {'type':'string','pattern':'^[a-z][a-z0-9_]{0,79}$','maxLength':80}
WAIT = integer(0,10000)
POLICY = obj({'version':{'type':'integer','const':1}, 'execution_mode':{'type':'string','enum':['noncombat','guarded','request_only']},
              'reactions':{'type':'string','enum':['stop','avoid','defend','defend_once']},
              'fall_rescue':obj({'schema_version':{'type':'integer','const':1},'water_bucket':{'type':'boolean','const':True}},('schema_version','water_bucket')),
              'defense':obj({'target_uuid':{'type':'string','pattern':'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'},
                  'timeout_ms':integer(50,5000), 'min_health':{'type':'number','minimum':14,'maximum':20}},
                  ('target_uuid','timeout_ms','min_health'))}, ('version','execution_mode'))
POLICY['allOf'] = [{'if':{'properties':{'reactions':{'const':'defend_once'}},'required':['reactions']},
    'then':{'required':['defense'], 'properties':{'execution_mode':{'enum':['guarded','request_only']}}},
    'else':{'not':{'required':['defense']}}}]
BUDGETS = obj({'deadline_seconds':integer(1,86400),'max_actions':integer(1,32768),'max_observations':integer(1,32768),
               'reflex_reserve_actions':integer(0,32768),'cleanup_reserve_actions':integer(0,32768)}, ('deadline_seconds','max_actions'))
SELECTORS = obj({'item_ids':{'type':'array','items':string(128),'maxItems':64}, 'entity_ids':{'type':'array','items':string(128),'maxItems':64},
                 'slots':{'type':'array','items':integer(0,255),'maxItems':256}, 'query':string(256)})
BOUNDS = obj({'radius':integer(1,32),'max_cells':integer(1,32768),'max_entities':integer(1,256),'max_results':integer(1,256)})
BASE = {'api_version':VERSION}
INTENT = {'capability':CAPABILITY,'capability_version':{'type':'integer','const':1},'arguments':{'type':'object'},'policy':POLICY,'budgets':BUDGETS}
CATALOG_SCHEMA = obj({**BASE,'group':string(64),'capability_ids':{'type':'array','items':CAPABILITY,'maxItems':128,'uniqueItems':True},
                      'detail':{'type':'string','enum':['summary','contracts']},'cursor':{'type':'string','pattern':'^[0-9]{1,8}$'},'limit':integer(1,128)}, ('api_version',))
OBSERVE_SCHEMA = obj({**BASE,'request_id':IDENTIFIER,'original_job_id':IDENTIFIER,'session_ref':REFERENCE,'profile':{'type':'string','enum':list(PROFILES)},'selectors':SELECTORS,'bounds':BOUNDS,
                      'acquisition_profile':string(80),'wait_ms':WAIT},('api_version','session_ref','profile'))
OBSERVE_SCHEMA['allOf']=[{'if':{'properties':{'profile':{'const':'reconciliation'}},'required':['profile']},
    'then':{'required':['original_job_id'],'properties':{'bounds':obj({'radius':{'const':1}}),
        'selectors':obj({}),'wait_ms':{'const':0}},'not':{'required':['acquisition_profile']}},
    'else':{'not':{'required':['original_job_id']}}}]
PLAN_SCHEMA = obj({**BASE,**INTENT,'session_ref':REFERENCE,'observation_refs':{'type':'array','items':REFERENCE,'maxItems':16}},
                   ('api_version','capability','capability_version','arguments'))
JOB_OPERATION_SCHEMAS = {
 'submit':obj({**BASE,**INTENT,'operation':{'const':'submit'},'request_id':IDENTIFIER,'session_ref':REFERENCE,'expected_context_ref':REFERENCE,
               'plan_ref':REFERENCE,'wait_ms':WAIT},('api_version','operation','request_id','session_ref','expected_context_ref','capability','capability_version','arguments','policy','budgets')),
 'status':obj({**BASE,'operation':{'const':'status'},'session_ref':REFERENCE,'job_id':IDENTIFIER,'request_id':IDENTIFIER,'event_cursor':integer(0,2147483647),'wait_ms':WAIT},('api_version','operation','session_ref')),
 'cancel':obj({**BASE,'operation':{'const':'cancel'},'session_ref':REFERENCE,'job_id':IDENTIFIER,'cancel_request_id':IDENTIFIER,'reason':string(256),'wait_ms':WAIT},('api_version','operation','session_ref','job_id','cancel_request_id')),
 'reconcile':obj({**BASE,'operation':{'const':'reconcile'},'session_ref':REFERENCE,'job_id':IDENTIFIER},('api_version','operation','session_ref','job_id')),
}
for operation in ('adjudication_prepare','adjudicate','adjudication_status'):
    properties={**BASE,'operation':{'const':operation},'session_ref':REFERENCE,'job_id':IDENTIFIER}
    required=['api_version','operation','session_ref','job_id']
    if operation!='adjudication_prepare':
        properties.update(adjudication_request_id=IDENTIFIER,
            original_receipt_sha256={'type':'string','pattern':'^[0-9a-f]{64}$','maxLength':64},
            acknowledgment={'type':'string','const':'release_authority_keep_original_effects_unknown_no_resume'})
        required+=['adjudication_request_id','original_receipt_sha256','acknowledgment']
    JOB_OPERATION_SCHEMAS[operation]=obj(properties,required)
JOB_OPERATION_SCHEMAS['status']['oneOf'] = [{'required':['job_id'],'not':{'required':['request_id']}},{'required':['request_id'],'not':{'required':['job_id']}}]
JOB_SCHEMA = obj({key:deepcopy(value) for schema in JOB_OPERATION_SCHEMAS.values() for key,value in schema['properties'].items()}, ('api_version','operation','session_ref'))
JOB_SCHEMA['properties']['operation'] = {'type':'string','enum':list(JOB_OPERATION_SCHEMAS)}
JOB_SCHEMA['allOf'] = [{'if':{'properties':{'operation':{'const':operation}}},'then':schema} for operation,schema in JOB_OPERATION_SCHEMAS.items()]
TOOL_SCHEMAS = {'mdc_catalog':CATALOG_SCHEMA,'mdc_observe':OBSERVE_SCHEMA,'mdc_plan':PLAN_SCHEMA,'mdc_job':JOB_SCHEMA}

def validate_call(name, arguments):
    if type(name) is not str or name not in TOOL_SCHEMAS: raise ToolboxError('invalid_request','Unknown toolbox tool')
    if isinstance(arguments,dict) and arguments.get('api_version') != API_VERSION:
        raise ToolboxError('unsupported_version','api_version must be mdc.toolbox/1')
    if isinstance(arguments,dict) and 'capability_version' in arguments and type(arguments['capability_version']) is int and arguments['capability_version'] != 1:
        raise ToolboxError('unsupported_version','Unsupported capability version')
    validate_schema(arguments,TOOL_SCHEMAS[name])
    budgets = arguments.get('budgets',{})
    if budgets.get('reflex_reserve_actions',0) + budgets.get('cleanup_reserve_actions',0) > budgets.get('max_actions',32768):
        raise ToolboxError('invalid_request','Budget reserves exceed the original total')
    return deepcopy(arguments)
