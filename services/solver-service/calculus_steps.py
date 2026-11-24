"""Worked solutions for derivatives and integrals.

Every step is {"rule": "Product rule", "text": "what happens and why", "math": "the expression"}.

Derivatives are done here, rule by rule (sum, constant multiple, product, quotient, power, chain and the
standard functions). Integrals use SymPy's own rule tree (sympy.integrals.manualintegrate), which names the
method it used (substitution, by parts, ...); this file turns that tree into sentences.

Both are checked before they are returned: the derivative must agree with SymPy's, and the antiderivative
must differentiate back to the integrand. If a result fails that check, no steps are shown for it.
"""
import re

import sympy as sp
from sympy.calculus.util import continuous_domain
from sympy.integrals import manualintegrate as mi

from expr import sympy_text

MAX_STEPS = 30
SAMPLE_POINTS = (0.37, 0.91, 1.43, 2.17, 3.3, -0.6, -1.7)


class Unsupported(Exception):
    """This form is beyond what the solver can show. The message is shown to the user."""


def text(expression):
    shown = sympy_text(sp.sympify(expression))
    shown = re.sub(r"(?<![A-Za-z])exp\((\d+|[A-Za-z])\)", r"e^\1", shown)   # exp(2) -> e^2, exp(x) -> e^x
    return re.sub(r"(?<![A-Za-z])exp\(", "e^(", shown)                       # exp(2x + 1) -> e^(2x + 1)


class Steps(list):
    def add(self, rule, explanation, math=None, matrix=None):
        if len(self) >= MAX_STEPS:
            raise Unsupported("This takes too many steps to show. Try a smaller expression.")
        step = {"rule": rule, "text": explanation, "math": math}
        if matrix is not None:
            step["matrix"] = matrix
        self.append(step)


def agree(first, second, symbol):
    """Do two expressions give the same numbers? (Sampled at a few points; complex or undefined points are skipped.)"""
    compared = 0
    for point in SAMPLE_POINTS:
        try:
            a = complex(first.subs(symbol, point).evalf(15))
            b = complex(second.subs(symbol, point).evalf(15))
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            continue
        if any(v != v or abs(v) == float("inf") for v in (a.real, a.imag, b.real, b.imag)):
            continue
        if abs(a.imag) > 1e-9 or abs(b.imag) > 1e-9:
            continue
        if abs(a - b) > 1e-6 * max(1.0, abs(a), abs(b)):
            return False
        compared += 1
    return compared >= 1


def tidy(expression):
    """The shortest of the plain, simplified and expanded forms (when SymPy can find them cheaply)."""
    if sp.count_ops(expression) > 150:
        return expression
    candidates = [expression]
    for rewrite in (sp.simplify, sp.expand):
        try:
            candidates.append(rewrite(expression))
        except Exception:  # noqa: BLE001 - these can fail in many ways; the plain form is still right
            pass
    return min(candidates, key=lambda c: (sp.count_ops(c), len(sp.sstr(c))))


# ---------------------------------------------------------------------------
# Derivatives
# ---------------------------------------------------------------------------

# outer function -> (name for the text, derivative of f(u) with respect to u)
_STANDARD = {
    sp.sin: ("sin", lambda u: sp.cos(u)),
    sp.cos: ("cos", lambda u: -sp.sin(u)),
    sp.tan: ("tan", lambda u: 1 / sp.cos(u) ** 2),
    sp.cot: ("cot", lambda u: -1 / sp.sin(u) ** 2),
    sp.sec: ("sec", lambda u: sp.sec(u) * sp.tan(u)),
    sp.csc: ("csc", lambda u: -sp.csc(u) * sp.cot(u)),
    sp.exp: ("e^", lambda u: sp.exp(u)),
    sp.log: ("ln", lambda u: 1 / u),
    sp.asin: ("asin", lambda u: 1 / sp.sqrt(1 - u ** 2)),
    sp.acos: ("acos", lambda u: -1 / sp.sqrt(1 - u ** 2)),
    sp.atan: ("atan", lambda u: 1 / (1 + u ** 2)),
    sp.sinh: ("sinh", lambda u: sp.cosh(u)),
    sp.cosh: ("cosh", lambda u: sp.sinh(u)),
    sp.tanh: ("tanh", lambda u: 1 / sp.cosh(u) ** 2),
    sp.asinh: ("asinh", lambda u: 1 / sp.sqrt(u ** 2 + 1)),
    sp.acosh: ("acosh", lambda u: 1 / sp.sqrt(u ** 2 - 1)),
    sp.atanh: ("atanh", lambda u: 1 / (1 - u ** 2)),
    sp.Abs: ("abs", lambda u: sp.sign(u)),
}


def _name(symbol):
    return str(symbol)


def _d(f, x, s, depth=0):
    """Differentiate f, adding the reasoning to s. Returns the derivative."""
    if depth > 14:
        raise Unsupported("This expression is nested too deeply to show step by step.")
    d = f"d/d{_name(x)}"

    if not f.has(x):
        s.add("Constant rule", f"{text(f)} does not contain {_name(x)}, so its derivative is 0.")
        return sp.Integer(0)

    if f == x:
        s.add("Variable rule", f"{d}[{_name(x)}] = 1.")
        return sp.Integer(1)

    if f.is_Add:
        moving = [term for term in f.args if term.has(x)]
        note = " (terms without " + _name(x) + " have derivative 0 and drop out)" if len(moving) < len(f.args) else ""
        s.add("Sum rule", "The derivative of a sum is the sum of the derivatives, so differentiate each term" + note + ".",
              " + ".join(f"{d}[{text(term)}]" for term in moving))
        parts = [_d(term, x, s, depth + 1) for term in moving]
        total = sp.Add(*parts)
        s.add("Add the pieces", "Put the derivatives of the terms back together.", text(total))
        return total

    if f.is_Mul:
        constant, rest = f.as_independent(x)
        if constant != 1:
            s.add("Constant multiple rule", f"A constant factor stays in front: {d}[c·g] = c·g'. Here c = {text(constant)}.",
                  f"{text(constant)}·{d}[{text(rest)}]")
            return constant * _d(rest, x, s, depth + 1)

        denominators = [a for a in f.args if a.is_Pow and a.exp.is_Integer and a.exp < 0 and a.base.has(x)]
        if len(denominators) == 1:
            bottom = denominators[0].base ** (-denominators[0].exp)
            top = sp.Mul(*[a for a in f.args if a is not denominators[0]])
            if top.has(x):
                s.add("Quotient rule", "For a fraction u/v, the derivative is (u'·v − u·v') / v².",
                      f"u = {text(top)},   v = {text(bottom)}")
                du = _d(top, x, s, depth + 1)
                dv = _d(bottom, x, s, depth + 1)
                result = (du * bottom - top * dv) / bottom ** 2
                s.add("Apply the quotient rule", "Substitute u, v, u' and v'.", text(result))
                return result

        first, others = f.args[0], sp.Mul(*f.args[1:])
        s.add("Product rule", "The derivative of u·v is u'·v + u·v'.", f"u = {text(first)},   v = {text(others)}")
        du = _d(first, x, s, depth + 1)
        dv = _d(others, x, s, depth + 1)
        result = du * others + first * dv
        s.add("Apply the product rule", "Substitute u, v, u' and v'.", text(result))
        return result

    if f.is_Pow:
        base, power = f.as_base_exp()
        if not power.has(x):
            if base == x:
                result = power * x ** (power - 1)
                s.add("Power rule", f"{d}[{_name(x)}^n] = n·{_name(x)}^(n−1), with n = {text(power)}.", text(result))
                return result
            s.add("Power rule with the chain rule",
                  f"{d}[g^n] = n·g^(n−1)·g'. Here g = {text(base)} and n = {text(power)}.",
                  f"{text(power * base ** (power - 1))}·{d}[{text(base)}]")
            return power * base ** (power - 1) * _d(base, x, s, depth + 1)
        if not base.has(x):
            s.add("Exponential rule", f"{d}[a^g] = a^g·ln(a)·g'. Here a = {text(base)} and g = {text(power)}.",
                  f"{text(f * sp.log(base))}·{d}[{text(power)}]")
            return f * sp.log(base) * _d(power, x, s, depth + 1)
        s.add("Logarithmic differentiation", "Both the base and the power contain "
              f"{_name(x)}: {d}[g^h] = g^h·(h'·ln g + h·g'/g).", f"g = {text(base)},   h = {text(power)}")
        dg = _d(base, x, s, depth + 1)
        dh = _d(power, x, s, depth + 1)
        return f * (dh * sp.log(base) + power * dg / base)

    if f.func in _STANDARD:
        label, rule = _STANDARD[f.func]
        inner = f.args[0]
        outer = rule(inner)
        shown = f"{label}({text(inner)})" if label != "e^" else f"e^({text(inner)})"
        if inner == x:
            s.add("Standard derivative", f"{d}[{shown}] = {text(outer)}.")
            return outer
        s.add("Chain rule", f"For f(g): {d}[f(g)] = f'(g)·g'. Here f is {label.rstrip('^')} and g = {text(inner)}, "
              f"so f'(g) = {text(outer)}.", f"{text(outer)}·{d}[{text(inner)}]")
        return outer * _d(inner, x, s, depth + 1)

    s.add("Direct", f"There is no named rule for {text(f)} here, so SymPy differentiates it directly.")
    return sp.diff(f, x)


def differentiate(f, x, at=None):
    """-> (answer expression, steps). Raises Unsupported when the working can't be shown."""
    reference = sp.diff(f, x)
    steps = Steps()
    working = _d(f, x, steps)
    if not agree(working, reference, x):
        raise Unsupported("The step-by-step working could not be verified for this expression.")
    answer = tidy(working)
    steps.add("Simplify", "Tidy the result.", f"d/d{_name(x)}[{text(f)}] = {text(answer)}")
    if at is not None:
        point = sp.nsimplify(at)
        value = answer.subs(x, point)
        if not value.is_finite:
            raise Unsupported(f"The derivative is not defined at {_name(x)} = {text(point)}.")
        steps.add("Evaluate", f"Substitute {_name(x)} = {text(point)} into the derivative.",
                  f"f'({text(point)}) = {text(sp.nsimplify(value))}" + ("" if value.is_Rational else f" ≈ {float(value):.6g}"))
    return answer, steps


# ---------------------------------------------------------------------------
# Integrals
# ---------------------------------------------------------------------------

_NAMES = {
    "Sec2Rule": "Standard integral", "Csc2Rule": "Standard integral", "SecTanRule": "Standard integral",
    "CscCotRule": "Standard integral", "SinRule": "Standard integral", "CosRule": "Standard integral",
    "SinhRule": "Standard integral", "CoshRule": "Standard integral", "ArctanRule": "Standard integral",
    "ArcsinRule": "Standard integral", "ExpRule": "Exponential rule", "ReciprocalRule": "Reciprocal rule",
    "TrigRule": "Trigonometric identity", "TrigSubstitutionRule": "Trigonometric substitution",
    "CompleteSquareRule": "Complete the square", "RewriteRule": "Rewrite the integrand",
}


def _antiderivative(integrand, x):
    return mi.manualintegrate(integrand, x)


def _narrate(rule, s, x):
    kind = type(rule).__name__
    integrand = rule.integrand
    variable = rule.variable
    shown = f"∫ {text(integrand)} d{_name(variable)}"

    if kind == "DontKnowRule":
        raise Unsupported("There is no closed-form antiderivative that can be shown step by step.")

    if kind == "ConstantRule":
        s.add("Constant rule", f"The integral of a constant is the constant times {_name(variable)}.",
              f"{shown} = {text(integrand * variable)}")
    elif kind == "ConstantTimesRule":
        s.add("Constant multiple rule", f"Take the constant {text(rule.constant)} out of the integral.",
              f"{text(rule.constant)}·∫ {text(rule.other)} d{_name(variable)}")
        _narrate(rule.substep, s, x)
    elif kind == "PowerRule":
        if rule.base == variable and rule.exp != -1:
            s.add("Power rule", f"∫ {_name(variable)}^n d{_name(variable)} = {_name(variable)}^(n+1)/(n+1) with n = {text(rule.exp)}.",
                  f"{shown} = {text(variable ** (rule.exp + 1) / (rule.exp + 1))}")
        else:
            s.add("Power rule", "Raise the power by one and divide by the new power.",
                  f"{shown} = {text(_antiderivative(integrand, variable))}")
    elif kind == "AddRule":
        s.add("Sum rule", "Integrate each term separately and add the results.",
              " + ".join(f"∫ {text(sub.integrand)} d{_name(variable)}" for sub in rule.substeps))
        for sub in rule.substeps:
            _narrate(sub, s, x)
    elif kind == "URule":
        du = sp.diff(rule.u_func, variable)
        s.add("Substitution", f"Let {text(rule.u_var)} = {text(rule.u_func)}. Then d{text(rule.u_var)} = {text(du)} d{_name(variable)}, "
              f"which turns the integral into one in {text(rule.u_var)}.",
              f"∫ {text(rule.substep.integrand)} d{text(rule.u_var)}")
        _narrate(rule.substep, s, x)
        s.add("Substitute back", f"Replace {text(rule.u_var)} by {text(rule.u_func)}.",
              f"{shown} = {text(_antiderivative(integrand, variable))}")
    elif kind == "PartsRule":
        v = _antiderivative(rule.dv, variable)
        s.add("Integration by parts", "∫ u dv = u·v − ∫ v du. Pick u so that it gets simpler when differentiated.",
              f"u = {text(rule.u)},   dv = {text(rule.dv)} d{_name(variable)}   so   du = {text(sp.diff(rule.u, variable))} d{_name(variable)},   v = {text(v)}")
        s.add("Now integrate v du", "What is left is a simpler integral.", f"∫ {text(rule.second_step.integrand)} d{_name(variable)}")
        _narrate(rule.second_step, s, x)
    elif kind == "CyclicPartsRule":
        s.add("Integration by parts, repeated", "Apply parts twice. The original integral comes back, so solve for it.",
              f"{shown} = {text(_antiderivative(integrand, variable))}")
    elif kind == "AlternativeRule":
        _narrate(rule.alternatives[0], s, x)
    elif kind == "RewriteRule":
        s.add("Rewrite the integrand", "Rewrite it in a form that is easier to integrate.",
              f"{text(integrand)} = {text(rule.rewritten)}")
        _narrate(rule.substep, s, x)
    elif kind == "CompleteSquareRule":
        s.add("Complete the square", "Rewrite the quadratic as a square plus a constant.",
              f"{text(integrand)} = {text(rule.rewritten)}")
        _narrate(rule.substep, s, x)
    elif kind == "ReciprocalRule":
        s.add("Reciprocal rule", f"The integral of 1/g with g = {text(rule.base)} is ln|g|.",
              f"{shown} = ln|{text(rule.base)}|")
    elif kind == "ExpRule":
        if rule.base == sp.E:
            s.add("Exponential rule", f"∫ e^{_name(variable)} d{_name(variable)} = e^{_name(variable)}.")
        else:
            s.add("Exponential rule", f"∫ a^{_name(variable)} d{_name(variable)} = a^{_name(variable)}/ln(a), with a = {text(rule.base)}.",
                  f"{shown} = {text(_antiderivative(integrand, variable))}")
    else:
        label = _NAMES.get(kind) or re.sub(r"(?<!^)(?=[A-Z])", " ", kind.replace("Rule", "")).strip().capitalize()
        s.add(label, "A standard result.", f"{shown} = {text(_antiderivative(integrand, variable))}")


def integrate(f, x, lower=None, upper=None):
    """-> (answer text, number or None, steps). Indefinite when lower and upper are None."""
    steps = Steps()
    try:
        rule = mi.integral_steps(f, x)
    except Exception as exc:  # noqa: BLE001 - SymPy raises many things for forms it can't handle
        raise Unsupported("This integral can't be worked out step by step.") from exc
    _narrate(rule, steps, x)

    antiderivative = _antiderivative(f, x)
    if antiderivative.has(sp.Integral) or not agree(sp.diff(antiderivative, x), f, x):
        raise Unsupported("The step-by-step working could not be verified for this integral.")
    shown = tidy(antiderivative)

    if lower is None:
        steps.add("Add the constant", "An indefinite integral always has a constant of integration"
                  + (" (for negative values, ln(g) means ln|g|)." if "ln(" in text(shown) else "."),
                  f"∫ {text(f)} d{_name(x)} = {text(shown)} + C")
        return f"{text(shown)} + C", None, steps

    interval = sp.Interval(min(lower, upper), max(lower, upper))
    try:
        domain = continuous_domain(f, x, interval)
    except Exception:  # noqa: BLE001
        domain = interval
    if domain != interval:
        raise Unsupported("The function is not defined everywhere between the limits, so this is an improper integral. "
                          "The solver only handles proper definite integrals.")
    top = shown.subs(x, upper)
    bottom = shown.subs(x, lower)
    value = sp.simplify(top - bottom)
    if not value.is_finite:
        raise Unsupported("The result is not a finite number.")
    steps.add("Fundamental theorem of calculus", "Evaluate the antiderivative at the upper and lower limits and subtract.",
              f"F({text(upper)}) − F({text(lower)}) = {text(top)} − ({text(bottom)})")
    number = float(value.evalf(15))
    steps.add("Subtract", "The area under the curve between the limits.",
              f"{text(value)}" + ("" if value.is_Integer or value.is_Rational else f" ≈ {number:.6g}"))
    return text(value), number, steps
