"""Safe maths expression engine used by math-service.

It turns text such as "2sin(x)^2 + 3x" into a small syntax tree and evaluates
that tree with NumPy, so the same expression can be computed for one value
(the scientific calculator) or for thousands of values at once (graphs).

There is no eval() or exec() anywhere: the text is split into tokens and
parsed by hand, and only the functions, constants and variables listed in
this file can be used. Anything else is rejected with a readable message.
"""
import math
import re
from functools import lru_cache

import numpy as np

MAX_LENGTH = 300   # characters in one expression
MAX_DEPTH = 40     # nested brackets / function calls


class ExpressionError(ValueError):
    """The expression can't be understood. The message is shown to the user."""


# ---------------------------------------------------------------------------
# Functions and constants
# ---------------------------------------------------------------------------

def _snap(values):
    """sin(pi) is 1.2e-16 in floating point; show it as 0."""
    return np.where(np.abs(values) < 1e-15, 0.0, values)


def _angle_in(a, degrees):
    return np.deg2rad(a) if degrees else a


def _angle_out(a, degrees):
    return np.rad2deg(a) if degrees else a


def _sin(a, degrees):
    return _snap(np.sin(_angle_in(a, degrees)))


def _cos(a, degrees):
    return _snap(np.cos(_angle_in(a, degrees)))


def _tan(a, degrees):
    result = _snap(np.tan(_angle_in(a, degrees)))
    return np.where(np.abs(result) > 1e15, np.nan, result)  # tan(90°) is undefined


def _gamma_scalar(value):
    try:
        return math.gamma(value)
    except (ValueError, OverflowError):
        return math.nan


_gamma = np.vectorize(_gamma_scalar, otypes=[float])


def _is_whole(value):
    return math.isfinite(value) and value == math.floor(value)


def _comb_scalar(n, r):
    if not (_is_whole(n) and _is_whole(r)) or r < 0 or n < 0 or r > n:
        return math.nan
    n, r = int(n), int(r)
    if n <= 1000:
        try:
            return float(math.comb(n, r))
        except OverflowError:
            return math.nan
    log_value = math.lgamma(n + 1) - math.lgamma(r + 1) - math.lgamma(n - r + 1)
    return math.exp(log_value) if log_value < 709 else math.nan


def _perm_scalar(n, r):
    if not (_is_whole(n) and _is_whole(r)) or r < 0 or n < 0 or r > n:
        return math.nan
    n, r = int(n), int(r)
    if n <= 1000:
        try:
            return float(math.perm(n, r))
        except OverflowError:
            return math.nan
    log_value = math.lgamma(n + 1) - math.lgamma(n - r + 1)
    return math.exp(log_value) if log_value < 709 else math.nan


_comb = np.vectorize(_comb_scalar, otypes=[float])
_perm = np.vectorize(_perm_scalar, otypes=[float])


def _round(a, digits=0.0):
    digits = np.asarray(digits)
    if digits.size != 1 or not _is_whole(float(digits)) or not 0 <= float(digits) <= 12:
        return np.full(np.shape(a), np.nan)
    factor = 10.0 ** float(digits)
    return np.sign(a) * np.floor(np.abs(a) * factor + 0.5) / factor  # 2.5 rounds to 3, like a calculator


def _root(a, n):
    n = np.asarray(n, dtype=float)
    odd = (np.abs(np.mod(n, 2)) == 1)
    return np.where(odd & (a < 0), -np.power(np.abs(a), 1.0 / n), np.power(a, 1.0 / n))


def _log(a, base=None):
    if base is None:
        return np.log10(a)
    return np.log(a) / np.log(base)


# name: (implementation(degrees, *args) -> array, min args, max args, help text, example)
FUNCTIONS = {
    "sin": (lambda d, a: _sin(a, d), 1, 1, "Sine", "sin(30)"),
    "cos": (lambda d, a: _cos(a, d), 1, 1, "Cosine", "cos(60)"),
    "tan": (lambda d, a: _tan(a, d), 1, 1, "Tangent", "tan(45)"),
    "sec": (lambda d, a: 1.0 / _cos(a, d), 1, 1, "Secant, 1/cos", "sec(60)"),
    "csc": (lambda d, a: 1.0 / _sin(a, d), 1, 1, "Cosecant, 1/sin", "csc(30)"),
    "cot": (lambda d, a: _cos(a, d) / _sin(a, d), 1, 1, "Cotangent, cos/sin", "cot(45)"),
    "asin": (lambda d, a: _angle_out(np.arcsin(a), d), 1, 1, "Inverse sine", "asin(0.5)"),
    "acos": (lambda d, a: _angle_out(np.arccos(a), d), 1, 1, "Inverse cosine", "acos(0.5)"),
    "atan": (lambda d, a: _angle_out(np.arctan(a), d), 1, 1, "Inverse tangent", "atan(1)"),
    "atan2": (lambda d, y, x: _angle_out(np.arctan2(y, x), d), 2, 2, "Angle of the point (x, y)", "atan2(1, 1)"),
    "sinh": (lambda d, a: np.sinh(a), 1, 1, "Hyperbolic sine", "sinh(1)"),
    "cosh": (lambda d, a: np.cosh(a), 1, 1, "Hyperbolic cosine", "cosh(1)"),
    "tanh": (lambda d, a: np.tanh(a), 1, 1, "Hyperbolic tangent", "tanh(1)"),
    "asinh": (lambda d, a: np.arcsinh(a), 1, 1, "Inverse hyperbolic sine", "asinh(1)"),
    "acosh": (lambda d, a: np.arccosh(a), 1, 1, "Inverse hyperbolic cosine", "acosh(2)"),
    "atanh": (lambda d, a: np.arctanh(a), 1, 1, "Inverse hyperbolic tangent", "atanh(0.5)"),
    "sqrt": (lambda d, a: np.sqrt(a), 1, 1, "Square root", "sqrt(16)"),
    "cbrt": (lambda d, a: np.cbrt(a), 1, 1, "Cube root", "cbrt(27)"),
    "root": (lambda d, a, n: _root(a, n), 2, 2, "nth root", "root(32, 5)"),
    "exp": (lambda d, a: np.exp(a), 1, 1, "e to the power", "exp(1)"),
    "ln": (lambda d, a: np.log(a), 1, 1, "Natural logarithm", "ln(e)"),
    "log": (lambda d, a, b=None: _log(a, b), 1, 2, "Log base 10, or log(x, base)", "log(1000)"),
    "log2": (lambda d, a: np.log2(a), 1, 1, "Log base 2", "log2(8)"),
    "abs": (lambda d, a: np.abs(a), 1, 1, "Absolute value", "abs(-7)"),
    "sign": (lambda d, a: np.sign(a), 1, 1, "Sign: -1, 0 or 1", "sign(-3)"),
    "floor": (lambda d, a: np.floor(a), 1, 1, "Round down", "floor(2.7)"),
    "ceil": (lambda d, a: np.ceil(a), 1, 1, "Round up", "ceil(2.1)"),
    "round": (lambda d, a, n=0.0: _round(a, n), 1, 2, "Round, or round(x, decimals)", "round(3.14159, 2)"),
    "mod": (lambda d, a, b: np.where(b == 0, np.nan, np.mod(a, np.where(b == 0, 1.0, b))), 2, 2,
            "Remainder of a divided by b", "mod(17, 5)"),
    "min": (lambda d, *args: np.minimum.reduce(np.broadcast_arrays(*args)), 2, 10, "Smallest value", "min(3, 7, 1)"),
    "max": (lambda d, *args: np.maximum.reduce(np.broadcast_arrays(*args)), 2, 10, "Largest value", "max(3, 7, 1)"),
    "hypot": (lambda d, a, b: np.hypot(a, b), 2, 2, "Length of the hypotenuse", "hypot(3, 4)"),
    "gamma": (lambda d, a: _gamma(a), 1, 1, "Gamma function", "gamma(5)"),
    "nCr": (lambda d, n, r: _comb(n, r), 2, 2, "Combinations", "nCr(5, 2)"),
    "nPr": (lambda d, n, r: _perm(n, r), 2, 2, "Permutations", "nPr(5, 2)"),
}

ALIASES = {"arcsin": "asin", "arccos": "acos", "arctan": "atan", "log10": "log", "ncr": "nCr", "npr": "nPr",
           "Pi": "pi", "PI": "pi"}

CONSTANTS = {
    "pi": (math.pi, "π, about 3.14159"),
    "e": (math.e, "Euler's number, about 2.71828"),
    "tau": (2 * math.pi, "τ = 2π"),
    "phi": ((1 + math.sqrt(5)) / 2, "Golden ratio, about 1.61803"),
}

ANGLE_FUNCTIONS = {"sin", "cos", "tan", "sec", "csc", "cot", "asin", "acos", "atan", "atan2"}
INFIX_FUNCTIONS = {"nCr", "nPr"}


def function_catalogue():
    """For the UI's 'functions you can use' list."""
    return {
        "functions": [{"name": name, "description": spec[3], "example": spec[4]} for name, spec in FUNCTIONS.items()],
        "constants": [{"name": name, "description": spec[1]} for name, spec in CONSTANTS.items()],
        "operators": ["+", "-", "*", "/", "^ (power)", "! (factorial)", "% (percent, or remainder between two numbers)"],
    }


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"""
    (?P<num>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\*\*|[-+*/^%!(),])
  | (?P<space>\s+)
""", re.VERBOSE)

_UNICODE = {"π": "pi", "τ": "tau", "φ": "phi", "×": "*", "·": "*", "÷": "/", "−": "-", "–": "-",
            "²": "^2", "³": "^3", "√": "√"}


def _normalise(text):
    text = "".join(_UNICODE.get(ch, ch) for ch in text)
    # √2 -> sqrt(2), √x -> sqrt(x), √(…) -> sqrt(…)
    text = re.sub(r"√\s*(\d+(?:\.\d+)?|[A-Za-z_]\w*)", r"sqrt(\1)", text)
    return text.replace("√", "sqrt")


@lru_cache(maxsize=512)
def _split_name(name, known):
    """'xy' -> ('x', 'y'), 'pix' -> ('pi', 'x'). None if it can't be split into known names."""
    if name in known:
        return (name,)
    for size in range(len(name) - 1, 0, -1):
        head = name[:size]
        if head in known:
            rest = _split_name(name[size:], known)
            if rest:
                return (head,) + rest
    return None


def _tokenize(text, variables):
    known = frozenset(FUNCTIONS) | frozenset(CONSTANTS) | frozenset(variables) | frozenset(ALIASES)
    tokens = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            raise ExpressionError(f"'{text[position]}' can't be used in an expression")
        kind = match.lastgroup
        value = match.group(kind)
        if kind == "name":
            if len(value) > 30:
                raise ExpressionError(f"'{value[:12]}…' is not a known name")
            parts = _split_name(value, known) or _split_name(value.lower(), known)
            if parts is None:
                raise ExpressionError(_unknown_name_message(value, variables))
            for part in parts:
                tokens.append(("name", ALIASES.get(part, part), position))
        elif kind == "op":
            tokens.append(("op", "^" if value == "**" else value, position))
        elif kind == "num":
            tokens.append(("num", value, position))
        position = match.end()
    return tokens


def _unknown_name_message(name, variables):
    power = re.fullmatch(r"([A-Za-z])(\d+)", name)
    if power and power.group(1) in variables:
        letter, digits = power.groups()
        return f"Write {letter}^{digits} for a power, or {digits}{letter} to multiply"
    if len(name) == 1:
        if variables:
            allowed = " and ".join(sorted(variables))
            return f"'{name}' isn't a variable here. Use {allowed}"
        return f"'{name}' isn't a number or a known constant"
    return f"'{name}' isn't a known function or constant"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
#   sum     := product (("+" | "-") product)*
#   product := combine (("*" | "/" | "%") combine | <implicit> power)*
#   combine := unary (("nCr" | "nPr") unary)*   calculator style: 10 nCr 3 means nCr(10, 3)
#   unary   := ("-" | "+") unary | power
#   power   := postfix ("^" unary)?           right-associative: 2^3^2 = 2^9
#   postfix := primary ("!" | "%")*
#   primary := number | constant | variable | function "(" sum ("," sum)* ")" | "(" sum ")"
#
# Nodes are tuples: ("num", value, text), ("const", name), ("var", name),
# ("neg", a), ("add"|"sub"|"mul"|"div"|"mod"|"pow", a, b), ("fact", a),
# ("percent", a), ("call", name, [args]).

class _Parser:
    def __init__(self, text, variables):
        self.tokens = _tokenize(text, variables)
        self.variables = variables
        self.index = 0
        self.depth = 0

    def peek(self, offset=0):
        position = self.index + offset
        return self.tokens[position] if position < len(self.tokens) else None

    def at(self, *ops, offset=0):
        token = self.peek(offset)
        return token is not None and token[0] == "op" and token[1] in ops

    def starts_operand(self, offset=0):
        token = self.peek(offset)
        return token is not None and (token[0] in ("num", "name") or token[1] == "(")

    def take(self):
        token = self.tokens[self.index]
        self.index += 1
        return token

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExpressionError("The expression has too many nested brackets")

    def close_bracket(self):
        if self.at(")"):
            self.take()
        elif self.peek() is not None:  # a missing ")" at the very end is closed automatically
            raise ExpressionError(f"Expected ')' before '{self.peek()[1]}'")
        self.depth -= 1

    def parse(self):
        if not self.tokens:
            raise ExpressionError("Enter an expression")
        node = self.sum()
        if self.peek() is not None:
            token = self.peek()
            if token[1] == ")":
                raise ExpressionError("There's a ')' without a matching '('")
            raise ExpressionError(f"Unexpected '{token[1]}'")
        return node

    def sum(self):
        node = self.product()
        while self.at("+", "-"):
            op = self.take()[1]
            node = ("add" if op == "+" else "sub", node, self.product())
        return node

    def product(self):
        node = self.combine()
        while True:
            if self.at("*", "/"):
                op = self.take()[1]
                node = ("mul" if op == "*" else "div", node, self.combine())
            elif self.at("%") and self.starts_operand(1):
                self.take()
                node = ("mod", node, self.combine())
            elif self.starts_operand():           # implicit multiplication: 2x, 3(x+1), x sin(x)
                node = ("mul", node, self.power())
            else:
                return node

    def at_infix(self):
        """nCr or nPr used between two numbers, as on a calculator (10 nCr 3), not as nCr(10, 3)."""
        token = self.peek()
        return token is not None and token[0] == "name" and token[1] in INFIX_FUNCTIONS and not self.at("(", offset=1)

    def combine(self):
        node = self.unary()
        while self.at_infix():
            name = self.take()[1]
            if self.peek() is None:
                raise ExpressionError(f"Put a number after {name}, for example 10 {name} 3")
            node = ("call", name, [node, self.unary()])
        return node

    def unary(self):
        if self.at("-"):
            self.take()
            return ("neg", self.unary())
        if self.at("+"):
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        base = self.postfix()
        if self.at("^"):
            self.take()
            self.enter()
            exponent = self.unary()
            self.depth -= 1
            return ("pow", base, exponent)
        return base

    def postfix(self):
        node = self.primary()
        while True:
            if self.at("!"):
                self.take()
                node = ("fact", node)
            elif self.at("%") and not self.starts_operand(1):
                self.take()
                node = ("percent", node)
            else:
                return node

    def primary(self):
        token = self.peek()
        if token is None:
            raise ExpressionError("The expression ends too early")
        kind, value, _ = token
        if kind == "num":
            self.take()
            number = float(value)
            if not math.isfinite(number):
                raise ExpressionError(f"{value} is too large")
            return ("num", number, value)
        if kind == "name":
            self.take()
            if value in FUNCTIONS:
                return self.call(value)
            if value in CONSTANTS:
                return ("const", value)
            if value in self.variables:
                return ("var", value)
            raise ExpressionError(_unknown_name_message(value, self.variables))
        if value == "(":
            self.take()
            self.enter()
            node = self.sum()
            self.close_bracket()
            return node
        if value == ")":
            raise ExpressionError("Something is missing before ')'")
        raise ExpressionError(f"Something is missing before '{value}'")

    def call(self, name):
        if not self.at("("):
            example = FUNCTIONS[name][4]
            if name in INFIX_FUNCTIONS:
                raise ExpressionError(f"Write {example} or 5 {name} 2")
            raise ExpressionError(f"Put brackets after {name}, for example {example}")
        self.take()
        self.enter()
        if self.at(")"):
            raise ExpressionError(f"{name}() needs a value inside the brackets")
        args = [self.sum()]
        while self.at(","):
            self.take()
            args.append(self.sum())
        self.close_bracket()
        _, low, high, _, example = FUNCTIONS[name]
        if not low <= len(args) <= high:
            expected = f"{low}" if low == high else f"{low} to {high}"
            raise ExpressionError(f"{name} takes {expected} value{'s' if high > 1 else ''}, for example {example}")
        return ("call", name, args)


def parse(text, variables=()):
    """Parse an expression. variables: the names allowed, e.g. {"x"} or {"x", "y"}."""
    if not isinstance(text, str) or not text.strip():
        raise ExpressionError("Enter an expression")
    if len(text) > MAX_LENGTH:
        raise ExpressionError(f"Keep the expression under {MAX_LENGTH} characters")
    return _Parser(_normalise(text.strip()), frozenset(variables)).parse()


# ---------------------------------------------------------------------------
# Evaluation (NumPy, element by element)
# ---------------------------------------------------------------------------

def evaluate(node, env=None, degrees=False):
    """Evaluate a parsed expression. env maps variable names to numbers or NumPy arrays.

    Results that aren't real numbers (division by zero, sqrt(-1), …) come back as NaN.
    """
    with np.errstate(all="ignore"):
        result = _eval(node, env or {}, degrees)
    return np.asarray(result, dtype=float)


def _eval(node, env, degrees):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "const":
        return CONSTANTS[node[1]][0]
    if kind == "var":
        return np.asarray(env[node[1]], dtype=float)
    if kind == "neg":
        return -_eval(node[1], env, degrees)
    if kind == "fact":
        return _gamma(np.asarray(_eval(node[1], env, degrees), dtype=float) + 1.0)
    if kind == "percent":
        return _eval(node[1], env, degrees) / 100.0
    if kind == "call":
        implementation = FUNCTIONS[node[1]][0]
        args = [np.asarray(_eval(arg, env, degrees), dtype=float) for arg in node[2]]
        return implementation(degrees, *args)
    a = np.asarray(_eval(node[1], env, degrees), dtype=float)
    b = np.asarray(_eval(node[2], env, degrees), dtype=float)
    if kind == "add":
        return a + b
    if kind == "sub":
        return a - b
    if kind == "mul":
        return a * b
    if kind == "div":
        return np.where(b == 0, np.nan, a / np.where(b == 0, 1.0, b))
    if kind == "mod":
        return np.where(b == 0, np.nan, np.mod(a, np.where(b == 0, 1.0, b)))
    if kind == "pow":
        return np.power(a, b)
    raise ExpressionError(f"Unknown operation {kind}")


def uses_variable(node, name):
    if node[0] == "var":
        return node[1] == name
    if node[0] == "call":
        return any(uses_variable(arg, name) for arg in node[2])
    return any(isinstance(child, tuple) and uses_variable(child, name) for child in node[1:])


def uses_angles(node):
    """True if the expression uses a trig function, so degrees vs radians matters."""
    if node[0] == "call":
        return node[1] in ANGLE_FUNCTIONS or any(uses_angles(arg) for arg in node[2])
    return any(isinstance(child, tuple) and uses_angles(child) for child in node[1:])


# ---------------------------------------------------------------------------
# Printing: shows how the expression was understood, e.g. "2x" -> "2·x"
# ---------------------------------------------------------------------------

_PRECEDENCE = {"add": 1, "sub": 1, "mul": 2, "div": 2, "mod": 2, "neg": 3, "pow": 4, "fact": 5, "percent": 5}
_SYMBOLS = {"add": " + ", "sub": " − ", "mul": "·", "div": "/", "mod": " mod ", "pow": "^"}
_CONSTANT_TEXT = {"pi": "π", "tau": "τ", "phi": "φ", "e": "e"}


def to_text(node):
    kind = node[0]
    if kind == "num":
        return node[2]
    if kind == "const":
        return _CONSTANT_TEXT[node[1]]
    if kind == "var":
        return node[1]
    if kind == "call":
        return f"{node[1]}({', '.join(to_text(arg) for arg in node[2])})"
    if kind == "neg":
        return "−" + _wrap(node[1], 3)
    if kind in ("fact", "percent"):
        return _wrap(node[1], 6) + ("!" if kind == "fact" else "%")
    level = _PRECEDENCE[kind]
    if kind == "pow":   # right-associative
        return _wrap(node[1], level + 1) + "^" + _wrap(node[2], level)
    return _wrap(node[1], level) + _SYMBOLS[kind] + _wrap(node[2], level + 1)


def _wrap(node, level):
    text = to_text(node)
    return f"({text})" if _PRECEDENCE.get(node[0], 9) < level else text


# ---------------------------------------------------------------------------
# SymPy conversion (calculus): built node by node, never from text
# ---------------------------------------------------------------------------

class SymbolicUnsupported(Exception):
    """The expression uses something SymPy can't differentiate exactly (e.g. round)."""


def to_sympy(node, symbols):
    import sympy as sp

    kind = node[0]
    if kind == "num":
        return sp.Rational(node[2]) if len(node[2]) <= 25 else sp.Float(node[1])
    if kind == "const":
        return {"pi": sp.pi, "e": sp.E, "tau": 2 * sp.pi, "phi": sp.GoldenRatio}[node[1]]
    if kind == "var":
        return symbols[node[1]]
    if kind == "neg":
        return -to_sympy(node[1], symbols)
    if kind == "fact":
        return sp.factorial(to_sympy(node[1], symbols))
    if kind == "percent":
        return to_sympy(node[1], symbols) / 100
    if kind == "call":
        args = [to_sympy(arg, symbols) for arg in node[2]]
        name = node[1]
        mapping = {
            "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "sec": sp.sec, "csc": sp.csc, "cot": sp.cot,
            "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "sinh": sp.sinh, "cosh": sp.cosh,
            "tanh": sp.tanh, "asinh": sp.asinh, "acosh": sp.acosh, "atanh": sp.atanh, "sqrt": sp.sqrt,
            "exp": sp.exp, "ln": sp.log, "abs": sp.Abs, "sign": sp.sign, "floor": sp.floor,
            "ceil": sp.ceiling, "gamma": sp.gamma, "cbrt": sp.cbrt,
        }
        if name in mapping:
            return mapping[name](args[0])
        if name == "log":
            return sp.log(args[0], args[1]) if len(args) == 2 else sp.log(args[0], 10)
        if name == "log2":
            return sp.log(args[0], 2)
        if name == "atan2":
            return sp.atan2(args[0], args[1])
        if name == "root":
            return sp.root(args[0], args[1])
        if name == "hypot":
            return sp.sqrt(args[0] ** 2 + args[1] ** 2)
        if name == "min":
            return sp.Min(*args)
        if name == "max":
            return sp.Max(*args)
        if name == "nCr":
            return sp.binomial(args[0], args[1])
        if name == "nPr":
            return sp.ff(args[0], args[1])
        if name == "mod":
            return sp.Mod(args[0], args[1])
        raise SymbolicUnsupported(name)
    a = to_sympy(node[1], symbols)
    b = to_sympy(node[2], symbols)
    if kind == "add":
        return a + b
    if kind == "sub":
        return a - b
    if kind == "mul":
        return a * b
    if kind == "div":
        return a / b
    if kind == "mod":
        return sp.Mod(a, b)
    if kind == "pow":
        return a ** b
    raise SymbolicUnsupported(kind)


def sympy_text(expression):
    """SymPy expression -> readable text: 2*x**2*exp(x) -> 2x^2·exp(x)."""
    import sympy as sp

    # Numbers with more than 15 digits (from 10^308·x, say) are shown in scientific notation
    huge = {a: sp.Float(a, 10) for a in expression.atoms(sp.Rational) if abs(a.p) >= 10**15 or a.q >= 10**15}
    if huge:
        expression = expression.xreplace(huge)
    text = sp.sstr(expression)
    text = re.sub(r"\b(\d+)(?:\.(\d*?))?0*e([+-]?\d+)",    # 1.230000000e+17 -> 1.23×10^(17)
                  lambda m: f"{m.group(1)}{'.' + m.group(2) if m.group(2) else ''}×10^({int(m.group(3))})", text)
    text = text.replace("**", "^")
    text = re.sub(r"\blog\(", "ln(", text)          # SymPy's log is the natural log
    text = re.sub(r"\bAbs\(", "abs(", text)
    text = re.sub(r"\bceiling\(", "ceil(", text)
    text = text.replace("GoldenRatio", "φ")
    text = re.sub(r"\bpi\b", "π", text)
    text = re.sub(r"(?<![\w.^])(\d+(?:\.\d+)?)\*(?=[A-Za-zπφ(])", r"\1", text)   # 2*x -> 2x
    return text.replace("*", "·").replace("-", "−")
