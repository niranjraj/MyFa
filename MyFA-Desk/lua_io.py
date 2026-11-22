"""Read WoW SavedVariables files and write Lua data files. Standard library only."""
import re

_NUM = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_WS = re.compile(r"(?:\s+|--\[(=*)\[.*?\]\1\]|--[^\n]*)+", re.S)
_ESC = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
        "\\": "\\", '"': '"', "'": "'", "\n": "\n"}


class LuaParseError(ValueError):
    pass


class _Parser:
    def __init__(self, text):
        self.s = text
        self.i = 0
        self.n = len(text)

    def ws(self):
        m = _WS.match(self.s, self.i)
        if m:
            self.i = m.end()

    def peek(self):
        self.ws()
        return self.s[self.i] if self.i < self.n else ""

    def expect(self, ch):
        if self.peek() != ch:
            raise LuaParseError(f"expected {ch!r} at {self.i}, found {self.s[self.i:self.i + 20]!r}")
        self.i += 1

    def string(self):
        q = self.s[self.i]
        self.i += 1
        out = []
        s = self.s
        while True:
            j = self.i
            while j < self.n and s[j] != q and s[j] != "\\":
                j += 1
            out.append(s[self.i:j])
            if j >= self.n:
                raise LuaParseError("unterminated string")
            if s[j] == q:
                self.i = j + 1
                return "".join(out)
            c = s[j + 1]
            if c.isdigit():
                k = j + 1
                while k < j + 4 and k < self.n and s[k].isdigit():
                    k += 1
                out.append(chr(int(s[j + 1:k])))
                self.i = k
            elif c == "x":
                out.append(chr(int(s[j + 2:j + 4], 16)))
                self.i = j + 4
            elif c == "z":
                k = j + 2
                while k < self.n and s[k].isspace():
                    k += 1
                self.i = k
            else:
                out.append(_ESC.get(c, c))
                self.i = j + 2

    def value(self):
        c = self.peek()
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string()
        m = _NUM.match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            if t.lower().startswith(("0x", "-0x")):
                return int(t, 16)
            v = float(t)
            return int(v) if v.is_integer() and "." not in t and "e" not in t.lower() else v
        m = _IDENT.match(self.s, self.i)
        if m:
            self.i = m.end()
            word = m.group(0)
            if word == "true":
                return True
            if word == "false":
                return False
            if word == "nil":
                return None
            if word == "math.huge":
                return float("inf")
            raise LuaParseError(f"unexpected identifier {word!r}")
        raise LuaParseError(f"unexpected {self.s[self.i:self.i + 20]!r} at {self.i}")

    def table(self):
        self.expect("{")
        out = {}
        auto = 1
        while True:
            c = self.peek()
            if c == "}":
                self.i += 1
                break
            if c == "[" and self.s[self.i + 1] not in "[=":
                self.i += 1
                key = self.value()
                self.expect("]")
                self.expect("=")
                out[key] = self.value()
            else:
                m = _IDENT.match(self.s, self.i)
                save = self.i
                if m and m.group(0) not in ("true", "false", "nil"):
                    self.i = m.end()
                    if self.peek() == "=" and self.s[self.i + 1:self.i + 2] != "=":
                        self.i += 1
                        out[m.group(0)] = self.value()
                    else:
                        self.i = save
                        out[auto] = self.value()
                        auto += 1
                else:
                    out[auto] = self.value()
                    auto += 1
            c = self.peek()
            if c in ",;":
                self.i += 1
        return _maybe_list(out)


def _maybe_list(d):
    if d and all(isinstance(k, int) for k in d) and set(d) == set(range(1, len(d) + 1)):
        return [d[k] for k in range(1, len(d) + 1)]
    return d


def parse_saved_variables(text):
    """Return {global_name: value} for every top-level assignment in a SavedVariables file."""
    p = _Parser(text)
    out = {}
    while True:
        p.ws()
        if p.i >= p.n:
            return out
        m = _IDENT.match(p.s, p.i)
        if not m:
            raise LuaParseError(f"expected a variable name at {p.i}")
        p.i = m.end()
        p.expect("=")
        out[m.group(0)] = p.value()


def _lua_str(s):
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif o < 32 or o == 127:
            out.append("\\%03d" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def to_lua(v, indent=0):
    pad = "\t" * (indent + 1)
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(round(v, 4))
    if isinstance(v, str):
        return _lua_str(v)
    if isinstance(v, (list, tuple)):
        if not v:
            return "{}"
        inner = ",\n".join(pad + to_lua(x, indent + 1) for x in v)
        return "{\n" + inner + ",\n" + "\t" * indent + "}"
    if isinstance(v, dict):
        if not v:
            return "{}"
        parts = []
        for k, x in v.items():
            if isinstance(k, int):
                key = f"[{k}]"
            elif isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                key = k
            else:
                key = "[" + _lua_str(str(k)) + "]"
            parts.append(f"{pad}{key} = {to_lua(x, indent + 1)}")
        return "{\n" + ",\n".join(parts) + ",\n" + "\t" * indent + "}"
    raise TypeError(f"cannot write {type(v).__name__} to Lua")
