"""Test-only JVM class decoder; no Java execution."""
class ClassFile:
    def __init__(self, data):
        self.data, self.p, self.cp = data, 0, [None]
        assert self.u(4) == 0xcafebabe
        self.minor, self.major = self.u(2), self.u(2)
        count = self.u(2)
        while len(self.cp) < count:
            tag = self.u(1)
            if tag == 1:
                size = self.u(2); value = self.take(size).decode('utf-8', errors='replace')
            elif tag in (3, 4): value = (tag, self.u(4))
            elif tag in (5, 6):
                value = (tag, self.u(8)); self.cp.extend((value, None)); continue
            elif tag in (7, 8, 16, 19, 20): value = (tag, self.u(2))
            elif tag in (9, 10, 11, 12, 17, 18): value = (tag, self.u(2), self.u(2))
            elif tag == 15: value = (tag, self.u(1), self.u(2))
            else: raise AssertionError(('unknown constant pool tag', tag))
            self.cp.append(value)
        self.flags, self.name, self.super = self.u(2), self.ref(self.u(2)), self.ref(self.u(2))
        self.interfaces = [self.ref(self.u(2)) for _ in range(self.u(2))]
        self.fields = self.members()
        self.methods = self.members()
        self.attributes = self.attrs()
        assert self.p == len(data)
    def take(self, n):
        assert self.p + n <= len(self.data)
        value = self.data[self.p:self.p+n]; self.p += n; return value
    def u(self, n): return int.from_bytes(self.take(n), 'big')
    def ref(self, i):
        if i == 0: return None
        value = self.cp[i]
        if isinstance(value, str): return value
        if value[0] in (7, 8, 16, 19, 20): return self.ref(value[1])
        if value[0] in (9, 10, 11):
            return self.ref(value[1]) + '.' + self.ref(value[2])
        if value[0] == 12: return self.ref(value[1]) + ':' + self.ref(value[2])
        return str(value)
    def attrs(self):
        out = {}
        for _ in range(self.u(2)):
            name, length = self.ref(self.u(2)), self.u(4)
            assert name not in out
            out[name] = self.take(length)
        return out
    def members(self):
        out = []
        for _ in range(self.u(2)):
            out.append({'flags': self.u(2), 'name': self.ref(self.u(2)), 'descriptor': self.ref(self.u(2)), 'attributes': self.attrs()})
        return out
    def method(self, name):
        found = [method for method in self.methods if method['name'] == name]
        assert len(found) == 1, (self.name, name, len(found))
        return found[0]
    def code(self, name):
        attr = self.method(name)['attributes']['Code']
        length = int.from_bytes(attr[4:8], 'big')
        code = attr[8:8+length]
        # All audited provider methods must be straight-line/branch-only code without handlers.
        assert int.from_bytes(attr[8+length:10+length], 'big') == 0
        return code
    def memberref(self, code, offset): return self.ref(int.from_bytes(code[offset+1:offset+3], 'big'))


def instructions(cf, code):
    """Decode complete JVM instruction boundaries; never scan operands as opcodes."""
    widths = {**{op:2 for op in [0x10,0x12,*range(0x15,0x1a),*range(0x36,0x3b),0xa9,0xbc]},
              **{op:3 for op in [0x11,0x13,0x14,0x84,*range(0x99,0xa9),*range(0xb2,0xb9),0xbb,0xbd,0xc0,0xc1,0xc6,0xc7]},
              0xb9:5,0xba:5,0xc5:4,0xc8:5,0xc9:5}
    at, rows = 0, []
    while at < len(code):
        op=code[at]; width=widths.get(op,1)
        if op in (0xaa,0xab):
            base=(at+4)&~3
            if op==0xaa:
                low=int.from_bytes(code[base+4:base+8],'big',signed=True)
                high=int.from_bytes(code[base+8:base+12],'big',signed=True)
                width=base-at+12+4*(high-low+1)
            else:
                pairs=int.from_bytes(code[base+4:base+8],'big',signed=True)
                width=base-at+8+8*pairs
        elif op==0xc4: width=6 if code[at+1]==0x84 else 4
        assert at+width<=len(code)
        row={'offset':at,'opcode':hex(op),'operands_hex':code[at+1:at+width].hex()}
        if op in [*range(0xb2,0xba),0xbb,0xbd,0xc0,0xc1]: row['reference']=cf.ref(int.from_bytes(code[at+1:at+3],'big'))
        elif op==0x12: row['reference']=cf.ref(code[at+1])
        elif op in (0x13,0x14): row['reference']=cf.ref(int.from_bytes(code[at+1:at+3],'big'))
        rows.append(row);at+=width
    assert at==len(code)
    return rows

