import json
import math

class Invalid(ValueError):pass

def strict_json(raw):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise Invalid('duplicate key')
            out[key]=value
        return out
    def reject(_):raise Invalid('nonfinite number')
    try:
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=reject)
        def finite(v):
            if isinstance(v,float) and not math.isfinite(v):raise Invalid('nonfinite number')
            if isinstance(v,dict):
                for x in v.values():finite(x)
            if isinstance(v,list):
                for x in v:finite(x)
        finite(value);return value
    except (ValueError,UnicodeError,RecursionError):raise Invalid('invalid strict JSON') from None

def encode(value):return json.dumps(value,allow_nan=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def closed(value,keys):
    if not isinstance(value,dict) or set(value)!=set(keys):raise Invalid('closed object mismatch')

def integer(value,low=0,high=9223372036854775807):
    if type(value) is not int or not low<=value<=high:raise Invalid('integer bound mismatch')

def number(value,low=-30000000,high=30000000):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise Invalid('finite number bound mismatch')
