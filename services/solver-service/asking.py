"""Understand a question typed in plain English, and answer it.

    "EMI for 5 lakh at 9% for 3 years"      -> finance-service (and the worked formula)
    "convert 72 f to c"                     -> converter-service
    "derivative of x^2 sin x"               -> worked solution from this service
    "determinant of [[1,2],[3,4]]"          -> worked solution from this service
    "plot sin(x)"                           -> the Function plotter, filled in

It is rule-based (patterns, no AI model and no internet), so it is fast, free and gives the same answer every
time. When it can't tell what is being asked, it says so and shows examples.

The other microservices are reached through `backend`, an object with
    backend.call(service, path, payload=None, method="POST") -> (json body, served_by)
which raises ServiceProblem when that service doesn't answer. app.py provides it.
"""
import re
import time

import sympy as sp

import algebra_steps
import calculus_steps
import expr
import finance_steps
from calculus_steps import Unsupported, text as sym_text

MAX_QUESTION = 300

EXAMPLES = [
    "EMI for 5 lakh at 9% for 3 years",
    "18% GST on 2499",
    "convert 72 f to c",
    "derivative of x^2 sin(x)",
    "integrate x e^x from 0 to 2",
    "solve x^2 - 5x + 6 = 0",
    "determinant of [[2,1],[5,3]]",
    "inverse of [[2,1],[5,3]]",
    "plot sin(x)",
    "20% of 350",
    "sqrt(144) + 3^2",
]


class NotUnderstood(Exception):
    """The question isn't one this parser knows. The message says what to add."""


class ServiceProblem(Exception):
    """Another microservice didn't answer, or answered with an error."""

    def __init__(self, service, message, status=503):
        super().__init__(message)
        self.service = service
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Reading numbers: 5 lakh, 2.5 crore, 50k, 1,00,000
# ---------------------------------------------------------------------------

NUM = r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?|\.\d+"
MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5,
               "crore": 1e7, "crores": 1e7, "cr": 1e7, "million": 1e6, "mn": 1e6, "billion": 1e9}
MONEY = re.compile(rf"(?:rs\.?|inr|₹)?\s*({NUM})\s*(lakhs?|lacs?|crores?|cr|thousand|million|mn|billion|k|l)?(?![a-z0-9])", re.I)

WORD_OPERATORS = [
    (r"\bplus\b", "+"), (r"\bminus\b", "-"), (r"\b(?:times|multiplied by|x)\b(?=\s*\d)", "*"),
    (r"\b(?:divided by|over)\b", "/"), (r"\b(?:to the power of|raised to|power)\b", "^"),
    (r"\bsquared\b", "^2"), (r"\bcubed\b", "^3"),
]


def to_number(token):
    return float(token.replace(",", ""))


def read_amount(text):
    """The first money-like amount in text -> (value, matched text), or None."""
    for match in MONEY.finditer(text):
        value = to_number(match.group(1))
        word = (match.group(2) or "").lower()
        if word:
            value *= MULTIPLIERS[word]
        return value, match.group(0)
    return None


def clean_question(raw):
    question = raw.strip()
    question = re.sub(r"[?!]+$", "", question).strip()
    question = re.sub(r"\.$", "", question).strip()
    previous = None
    while previous != question:
        previous = question
        question = re.sub(
            r"^(?:hey|hi|hello|ok|okay)[ ,]+|^(?:please|pls|kindly)\s+|^(?:can|could|would) you\s+|"
            r"^(?:tell me|show me|work out|give me)\s+|^(?:calculate|compute|find|what(?:'s| is| are)|whats|how much is)\s+",
            "", question, flags=re.I).strip()
    return question


# ---------------------------------------------------------------------------
# Reading symbolic expressions
# ---------------------------------------------------------------------------

def pick_variable(source, default="x"):
    letters = set(re.findall(r"(?<![A-Za-z])([xyzt])(?![A-Za-z])", source))
    if len(letters) > 1:
        raise Unsupported("The solver works with one unknown at a time. Use only x, for example.")
    return (letters or {default}).pop()


def symbolic(source, variable="x", label="expression"):
    """text -> SymPy expression (using the same safe parser as math-service)."""
    source = source.strip()
    if not source:
        raise NotUnderstood(f"I need an {label}")
    if len(source) > expr.MAX_LENGTH:
        raise Unsupported(f"The {label} is too long")
    try:
        node = expr.parse(source, (variable,))
        return expr.to_sympy(node, {variable: sp.Symbol(variable)})
    except expr.ExpressionError as err:
        raise Unsupported(str(err)) from None
    except expr.SymbolicUnsupported as err:
        raise Unsupported(f"'{err}' can't be used in a worked solution") from None
    except (TypeError, ValueError, ZeroDivisionError, RecursionError):
        raise Unsupported(f"I couldn't read that {label}") from None


def bound(source):
    """A limit such as 3, -1.5, pi/2 -> SymPy number."""
    value = symbolic(source.strip(), "x", "limit")
    if value.has(sp.Symbol("x")):
        raise Unsupported("The limits must be numbers")
    return value


# ---------------------------------------------------------------------------
# Units: built from converter-service's /units, so every unit the converter knows can be named in a question
# ---------------------------------------------------------------------------

EXTRA_UNIT_WORDS = {
    "kilometers": "km", "kilometres": "km", "kilometer": "km", "kilometre": "km", "kms": "km", "kmh": "km/h", "kph": "km/h",
    "kmph": "km/h", "mph": "mph", "meters": "m", "metres": "m", "meter": "m", "metre": "m",
    "centimeters": "cm", "centimetres": "cm", "centimeter": "cm", "centimetre": "cm",
    "millimeters": "mm", "millimetres": "mm", "miles": "mi", "mile": "mi", "feet": "ft", "foot": "ft", "inches": "in",
    "inch": "in", "yards": "yd", "pounds": "lb", "pound": "lb", "lbs": "lb", "kilograms": "kg", "kilogram": "kg",
    "kilos": "kg", "kilo": "kg", "grams": "g", "gram": "g", "ounces": "oz", "ounce": "oz", "celsius": "c",
    "centigrade": "c", "fahrenheit": "f", "kelvin": "k", "degrees celsius": "c", "degrees fahrenheit": "f",
    "litres": "l", "liters": "l", "litre": "l", "liter": "l", "hours": "h", "hour": "h", "hrs": "h", "hr": "h",
    "minutes": "min", "minute": "min", "mins": "min", "seconds": "s", "second": "s", "secs": "s", "sec": "s",
    "days": "d", "day": "d", "weeks": "wk", "week": "wk", "years": "yr", "year": "yr",
    "gigabytes": "gb", "megabytes": "mb", "kilobytes": "kb", "terabytes": "tb", "gigabyte": "gb", "megabyte": "mb",
}

_units_cache = {"at": 0.0, "words": None}


def unit_words(categories):
    """word -> set of (category id, unit id)"""
    words = {}

    def add(word, category, unit):
        words.setdefault(word.lower().replace("°", "").strip(), set()).add((category, unit))

    for category in categories:
        for unit in category["units"]:
            add(unit["id"], category["id"], unit["id"])
            add(unit["symbol"], category["id"], unit["id"])
            name = unit["name"].lower()
            for variant in {name, name.replace("metre", "meter").replace("litre", "liter")}:
                add(variant, category["id"], unit["id"])
                add(variant + "s", category["id"], unit["id"])
    for word, unit_id in EXTRA_UNIT_WORDS.items():
        for category in categories:
            if any(unit["id"] == unit_id or unit["symbol"].lower() == unit_id for unit in category["units"]):
                match = next(unit for unit in category["units"] if unit["id"] == unit_id or unit["symbol"].lower() == unit_id)
                add(word, category["id"], match["id"])
    return words


def load_unit_words(backend):
    if _units_cache["words"] is None or time.time() - _units_cache["at"] > 3600:
        body, _ = backend.call("converter", "/units", method="GET")
        _units_cache.update(at=time.time(), words=unit_words(body["categories"]))
    return _units_cache["words"]


# ---------------------------------------------------------------------------
# One handler per kind of question. Each returns a dict, or None if the text isn't that kind.
# ---------------------------------------------------------------------------

def money(value):
    return finance_steps.inr(value, 0 if value == int(value) else 2)


def handle_emi(question, backend):
    if not re.search(r"\b(?:emi|loan|instal+ments?|mortgage)\b", question, re.I):
        return None
    tenure = re.search(rf"({NUM})\s*(years?|yrs?|months?|mos?)\b", question, re.I)
    rate = re.search(rf"({NUM})\s*(?:%|percent|per ?cent|pc\b|p\.?a\.?)", question, re.I) or \
        re.search(rf"(?:at|@|rate(?: of)?|interest(?: of)?)\s*({NUM})(?!\s*(?:years?|yrs?|months?|mos?|lakhs?|crores?|k\b))", question, re.I)
    rest = question
    for match in (tenure, rate):
        if match:
            rest = rest.replace(match.group(0), " ", 1)
    amount = read_amount(rest)
    needs = [label for label, found in (("the loan amount", amount), ("the yearly interest rate", rate), ("the time", tenure)) if not found]
    if needs:
        raise NotUnderstood("For an EMI I also need " + " and ".join(needs) + ", for example: EMI for 5 lakh at 9% for 3 years")
    unit = "years" if tenure.group(2).lower().startswith("y") else "months"
    return emi_result(amount[0], to_number(rate.group(1)), to_number(tenure.group(1)), unit, backend)


def emi_result(principal, annual, count, unit, backend):
    months = count * 12 if unit == "years" else count
    if abs(months - round(months)) > 1e-9:
        raise Unsupported("The time must be a whole number of months")
    months = int(round(months))

    numbers, steps = finance_steps.emi_steps(principal, annual, months)
    used, notes = [], []
    try:
        body, served = backend.call("finance", "/emi", {"principal": principal, "annual_rate": annual,
                                                        "tenure": count, "tenure_unit": unit})
        used.append({"service": "finance-service", "served_by": served})
        if abs(body["emi"] - numbers["emi"]) > 0.02 or abs(body["total_interest"] - numbers["total_interest"]) > 1:
            notes.append("finance-service gave a slightly different figure; its answer is the one shown.")
            numbers.update(emi=body["emi"], total_interest=body["total_interest"], total_payment=body["total_payment"])
        else:
            notes.append("finance-service worked it out too, and the figures match.")
    except ServiceProblem as problem:
        notes.append(f"{problem.service} isn't answering, so this is the worked solution only and wasn't saved to history.")
    return {
        "intent": "emi",
        "understood": f"EMI on {money(principal)} at {annual:g}% a year for {finance_steps.tenure_text(months)}",
        "answer": f"{finance_steps.inr(numbers['emi'])} a month",
        "details": [{"label": "Total interest", "value": finance_steps.inr(numbers["total_interest"])},
                    {"label": "Total payment", "value": finance_steps.inr(numbers["total_payment"])}],
        "steps": steps,
        "open": {"tool": "emi", "fields": {"emi-principal": principal, "emi-rate": annual, "emi-tenure": count},
                 "choices": {"tenure_unit": unit}},
        "used": used, "notes": notes,
    }


def handle_gst(question, backend):
    if not re.search(r"\bgst\b", question, re.I):
        return None
    rate = re.search(rf"({NUM})\s*(?:%|percent|per ?cent)", question, re.I) or re.search(rf"(?:at|@|rate(?: of)?)\s*({NUM})\b", question, re.I)
    rest = question.replace(rate.group(0), " ", 1) if rate else question
    amount = read_amount(re.sub(r"\bgst\b", " ", rest, flags=re.I))
    if not amount:
        raise NotUnderstood("For GST I need the amount, for example: 18% GST on 2499")
    inclusive = bool(re.search(r"\b(?:inclusive|including|incl|included|inclusion|remove|reverse|extract|already|with gst)\b", question, re.I)) \
        and not re.search(r"\b(?:exclusive|excluding|excl|add)\b", question, re.I)
    notes = []
    if rate:
        percent = to_number(rate.group(1))
    else:
        percent = 18.0
        notes.append("No rate was given, so I used 18%, the standard GST rate.")
    return gst_result(amount[0], percent, "inclusive" if inclusive else "exclusive", backend, notes)


def gst_result(amount_value, percent, mode, backend, notes):
    numbers, steps = finance_steps.gst_steps(amount_value, percent, mode)
    used = []
    try:
        body, served = backend.call("finance", "/gst", {"amount": amount_value, "rate": percent, "mode": mode, "supply": "intra"})
        used.append({"service": "finance-service", "served_by": served})
        if abs(body["gst_amount"] - numbers["gst"]) > 0.011:
            numbers.update(gst=body["gst_amount"], net=body["net_amount"], gross=body["gross_amount"])
            notes.append("finance-service rounded it slightly differently; its figures are shown.")
        else:
            notes.append("finance-service worked it out too, and the figures match.")
    except ServiceProblem as problem:
        notes.append(f"{problem.service} isn't answering, so this is the worked solution only and wasn't saved to history.")
    if mode == "exclusive":
        headline, understood = f"{finance_steps.inr(numbers['gross'])} in total", f"{percent:g}% GST added to {finance_steps.inr(amount_value)}"
    else:
        headline, understood = f"{finance_steps.inr(numbers['net'])} before GST", f"{finance_steps.inr(amount_value)} already includes {percent:g}% GST"
    return {
        "intent": "gst", "understood": understood, "answer": headline,
        "details": [{"label": "Price before GST", "value": finance_steps.inr(numbers["net"])},
                    {"label": f"GST at {percent:g}%", "value": finance_steps.inr(numbers["gst"])},
                    {"label": "Price with GST", "value": finance_steps.inr(numbers["gross"])}],
        "steps": steps,
        "open": {"tool": "gst", "fields": {"gst-amount": amount_value}, "choices": {"mode": mode}},
        "used": used, "notes": notes,
    }


def handle_units(question, backend):
    match = re.match(rf"^(?:convert\s+)?({NUM})\s*([a-z°µ/²³ ]+?)\s+(?:to|in|into|as|=)\s+([a-z°µ/²³ ]+)$", question, re.I)
    if not match:
        return None
    value = to_number(match.group(1))
    sign = -1 if re.search(r"(?:^|\s)(?:minus|negative)\s", question, re.I) else 1
    left, right = match.group(2).strip().lower(), match.group(3).strip().lower()
    words = load_unit_words(backend)
    left_units, right_units = words.get(left.replace("°", "")), words.get(right.replace("°", ""))
    if not left_units or not right_units:
        return None                         # not a unit question after all ("5 apples to oranges")
    shared = sorted({c for c, _ in left_units} & {c for c, _ in right_units})
    if not shared:
        raise Unsupported(f"{left} and {right} measure different things, so they can't be converted into each other")
    category = shared[0]
    from_unit = next(u for c, u in sorted(left_units) if c == category)
    to_unit = next(u for c, u in sorted(right_units) if c == category)
    body, served = backend.call("converter", "/convert", {"category": category, "value": sign * value,
                                                          "from_unit": from_unit, "to_unit": to_unit})
    return {
        "intent": "unit-converter",
        "understood": f"Convert {body['value']:g} {body['from_symbol']} to {body['to_symbol']}",
        "answer": f"{body['value']:g} {body['from_symbol']} = {body['result']:.10g} {body['to_symbol']}",
        "details": [{"label": body["category_name"], "value": body["summary"]}],
        "used": [{"service": "converter-service", "served_by": served}], "notes": [],
    }


def split_at(text):
    """'x^2 at x = 3' -> ('x^2', '3')"""
    match = re.search(r"\s+(?:at|when|for)\s+(?:[a-z]\s*=\s*)?(-?[\d.]+|-?\w*pi\w*)\s*$", text, re.I)
    return (text[:match.start()], match.group(1)) if match else (text, None)


def handle_derivative(question, backend):
    match = re.match(r"^(?:the\s+)?(?:derivative|differentiation|differentiate|diff|slope|gradient)(?:\s+(?:of|for))?\s*(.+)$", question, re.I) or \
        re.match(r"^d\s*/\s*d([a-z])\s*(?:of)?\s*(.+)$", question, re.I)
    if not match:
        return None
    body = match.group(match.lastindex)
    body = re.sub(r"\s+(?:with respect to|wrt|w\.r\.t\.?)\s+[a-z]\s*$", "", body, flags=re.I)
    body, at = split_at(body)
    return derivative_result(body, at)


def derivative_result(body, at=None):
    variable = pick_variable(body)
    f = symbolic(body, variable)
    x = sp.Symbol(variable)
    point = bound(at) if at else None
    answer, steps = calculus_steps.differentiate(f, x, point)
    details = []
    if point is not None:
        value = answer.subs(x, point)
        details.append({"label": f"At {variable} = {sym_text(point)}", "value": sym_text(sp.nsimplify(value))})
    return {
        "intent": "derivative",
        "understood": f"Derivative of {sym_text(f)} with respect to {variable}",
        "answer": f"d/d{variable} [{sym_text(f)}] = {sym_text(answer)}",
        "details": details, "steps": steps,
        "record": {"tool": "solver", "summary": f"d/d{variable}[{sym_text(f)}] = {sym_text(answer)}",
                   "input": {"kind": "derivative", "expression": body, "at": at}, "result": {"answer": sym_text(answer)}},
        "used": [], "notes": [],
    }


def handle_integral(question, backend):
    match = re.match(r"^(?:the\s+)?(?:integral|integration|integrate|antiderivative|area under(?: the curve)?)(?:\s+(?:of|for))?\s*(.+)$", question, re.I) \
        or re.match(r"^∫\s*(.+)$", question)
    if not match:
        return None
    body = match.group(1)
    limits = re.search(r"\s+(?:from|between)\s+(.+?)\s+(?:to|and)\s+(.+)$", body, re.I) or \
        re.search(r"\s+\[\s*(.+?)\s*,\s*(.+?)\s*\]$", body)
    lower_text = upper_text = None
    if limits:
        body = body[:limits.start()]
        lower_text, upper_text = limits.group(1), limits.group(2)
    return integral_result(body, lower_text, upper_text)


def integral_result(body, lower_text=None, upper_text=None):
    lower = bound(lower_text) if lower_text not in (None, "") else None
    upper = bound(upper_text) if upper_text not in (None, "") else None
    if (lower is None) != (upper is None):
        raise Unsupported("Give both limits, or none for an indefinite integral")
    body = re.sub(r"\s*d([a-z])\s*$", "", body.strip(), flags=re.I) if re.search(r"\s+d[xyzt]\s*$", body) else body
    variable = pick_variable(body)
    f = symbolic(body, variable)
    x = sp.Symbol(variable)
    answer, number, steps = calculus_steps.integrate(f, x, lower, upper)
    if lower is None:
        understood = f"Integral of {sym_text(f)} with respect to {variable}"
        headline = f"∫ {sym_text(f)} d{variable} = {answer}"
        details = []
    else:
        understood = f"Integral of {sym_text(f)} from {sym_text(lower)} to {sym_text(upper)}"
        headline = f"∫ from {sym_text(lower)} to {sym_text(upper)} of {sym_text(f)} d{variable} = {answer}"
        details = [{"label": "As a decimal", "value": f"{number:.8g}"}]
    return {
        "intent": "integral", "understood": understood, "answer": headline, "details": details, "steps": steps,
        "record": {"tool": "solver", "summary": headline,
                   "input": {"kind": "integral", "expression": body, "lower": None if lower is None else sym_text(lower),
                             "upper": None if upper is None else sym_text(upper)}, "result": {"answer": answer}},
        "used": [], "notes": [],
    }


def handle_equation(question, backend):
    match = re.match(r"^(?:solve|roots? of|zeros? of|find (?:the )?(?:roots?|zeros?|solutions?) of)\s*(?:the equation\s*)?:?\s*(.+)$", question, re.I)
    if match:
        body = match.group(1)
    elif "=" in question and re.search(r"[xyzt]", question) and not re.search(r"[<>]", question):
        body = question
    else:
        return None
    return equation_result(re.sub(r"\s+for\s+[a-z]\s*$", "", body, flags=re.I))


def equation_result(body):
    variable = pick_variable(body)
    sides = [part for part in body.replace("==", "=").split("=")]
    if len(sides) > 2:
        raise Unsupported("An equation has one = sign")
    left = symbolic(sides[0], variable)
    right = symbolic(sides[1], variable) if len(sides) == 2 and sides[1].strip() else sp.Integer(0)
    x = sp.Symbol(variable)
    solutions, steps = algebra_steps.solve_equation(left, right, x)
    shown = " and ".join(f"{variable} = {sym_text(v)}" for v in solutions[:6])
    details = []
    decimals = [algebra_steps.decimal_of(v) for v in solutions[:6]]
    if all(isinstance(d, float) for d in decimals) and any(not sp.sympify(v).is_Rational for v in solutions):
        details.append({"label": "As decimals", "value": ", ".join(f"{variable} ≈ {d:.6g}" for d in decimals)})
    return {
        "intent": "equation",
        "understood": f"Solve {sym_text(left)} = {sym_text(right)}",
        "answer": shown, "details": details, "steps": steps,
        "record": {"tool": "solver", "summary": f"Solve {sym_text(left)} = {sym_text(right)}: {shown}",
                   "input": {"kind": "equation", "equation": body}, "result": {"solutions": [sym_text(v) for v in solutions]}},
        "used": [], "notes": [],
    }


def matrix_result(operation, matrix_rows, constants=None):
    """Shared by /ask and /matrix-steps -> (answer text, details, steps, understood, resulting matrix or None)"""
    if operation == "determinant":
        value, steps = algebra_steps.determinant_steps(matrix_rows)
        return f"det = {algebra_steps.fraction_text(value)}", [], steps, "Determinant of the matrix", None
    if operation == "inverse":
        inverse, steps = algebra_steps.inverse_steps(matrix_rows)
        if inverse is None:
            return "No inverse: the matrix is singular (determinant 0)", [], steps, "Inverse of the matrix", None
        return "The inverse matrix is below", [], steps, "Inverse of the matrix", inverse
    if operation == "rref":
        reduced, steps, info = algebra_steps.rref_steps(matrix_rows)
        return f"Row echelon form found, rank {info['rank']}", [], steps, "Reduce the matrix to row echelon form", reduced
    if operation == "solve":
        solution, steps = algebra_steps.solve_steps(matrix_rows, constants)
        if solution is None:
            return "No single solution (see the last step)", [], steps, "Solve the system of equations", None
        names = ["x", "y", "z", "w", "v", "u"]
        return (",  ".join(f"{names[i]} = {algebra_steps.fraction_text(v)}" for i, v in enumerate(solution)),
                [], steps, "Solve the system of equations", None)
    raise Unsupported("Choose determinant, inverse, rref or solve")


def handle_matrix(question, backend):
    if not re.search(r"\b(?:determinant|det|inverse|invert|rref|row[- ]reduce|echelon|matrix)\b|\[\[", question, re.I):
        return None
    if re.search(r"\b(?:inverse|invert)\b", question, re.I):
        operation = "inverse"
    elif re.search(r"\b(?:determinant|det)\b", question, re.I):
        operation = "determinant"
    elif re.search(r"\b(?:rref|row[- ]reduce|echelon)\b", question, re.I):
        operation = "rref"
    else:
        raise NotUnderstood("For a matrix I need to know what to find: determinant, inverse or rref, for example: determinant of [[2,1],[5,3]]")
    literal = re.search(r"\[\s*\[.*\]\s*\]", question) or re.search(r"(?:of|for)\s+(.+)$", question, re.I)
    source = literal.group(0) if literal and literal.group(0).startswith("[") else (literal.group(1) if literal else "")
    rows = algebra_steps.matrix_from_text(source) if source else None
    if not rows:
        raise NotUnderstood("I couldn't find the matrix. Write it like [[2,1],[5,3]] or 2 1; 5 3")
    answer, details, steps, understood, resulting = matrix_result(operation, rows)
    return {
        "intent": operation, "understood": understood, "answer": answer, "details": details, "steps": steps, "matrix": resulting,
        "record": {"tool": "solver", "summary": f"{understood}: {answer}",
                   "input": {"kind": "matrix", "operation": operation, "matrix": [[str(c) for c in r] for r in rows]},
                   "result": {"answer": answer}},
        "open": {"tool": "matrices", "restore": {"operation": operation, "a": [[str(c) for c in r] for r in rows]}},
        "used": [], "notes": [],
    }


def handle_percent(question, backend):
    match = re.match(rf"^({NUM})\s*(?:%|percent|per ?cent)\s*of\s*(?:rs\.?|inr|₹)?\s*({NUM})\s*$", question, re.I)
    if not match:
        return None
    body, served = backend.call("calc", "/calculate", {"num1": to_number(match.group(1)), "num2": to_number(match.group(2)),
                                                       "operation": "percent_of"})
    return {
        "intent": "calculator", "understood": f"{match.group(1)}% of {match.group(2)}", "answer": body["expression"],
        "details": [], "used": [{"service": "calc-service", "served_by": served}], "notes": [],
    }


def handle_plot(question, backend):
    match = re.match(r"^(?:plot|graph|draw|sketch|visuali[sz]e)\s+(?:the\s+)?(?:function\s+|curve\s+|surface\s+)?(.+)$", question, re.I)
    if not match:
        return None
    body = re.sub(r"^(?:y|f\(x\)|z)\s*=\s*", "", match.group(1).strip(), flags=re.I)
    body = re.sub(r"\s+in\s+3d$", "", body, flags=re.I)
    three_d = bool(re.search(r"\b3d\b|\bsurface\b", question, re.I)) or bool(re.search(r"\by\b", body) and re.search(r"\bx\b", body))
    if three_d:
        body = re.sub(r"^3d\s+", "", body, flags=re.I)
        try:
            node = expr.parse(body, ("x", "y"))
        except expr.ExpressionError as err:
            raise Unsupported(str(err)) from None
        return {
            "intent": "graph3d", "understood": f"Draw the surface z = {expr.to_text(node)}",
            "answer": f"Drawing z = {expr.to_text(node)} in the 3D graph",
            "details": [], "open": {"tool": "graph3d", "fields": {"g3-z": body}, "choices": {"mode": "surface"}},
            "used": [], "notes": [], "hands_over": True,
        }
    try:
        node = expr.parse(body, ("x",))
    except expr.ExpressionError as err:
        raise Unsupported(str(err)) from None
    return {
        "intent": "plot2d", "understood": f"Draw y = {expr.to_text(node)}", "answer": f"Drawing y = {expr.to_text(node)} in the function plotter",
        "details": [], "open": {"tool": "plotter", "fields": {"fn-0": body}},
        "used": [], "notes": [], "hands_over": True,
    }


def handle_arithmetic(question, backend):
    text = question
    for pattern, replacement in WORD_OPERATORS:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r"\b(?:what is|equals?|=)\s*$", "", text, flags=re.I).strip()
    if not re.search(r"\d|\bpi\b|\be\b", text, re.I):
        return None
    try:
        expr.parse(text, ("ans",))
    except expr.ExpressionError:
        return None
    body, served = backend.call("math", "/evaluate", {"expression": text, "angle": "deg"})
    return {
        "intent": "scientific", "understood": f"Calculate {body['interpreted']}", "answer": body["summary"],
        "details": [], "open": {"tool": "scientific", "fields": {"sci-expression": text}},
        "used": [{"service": "math-service", "served_by": served}], "notes": [],
    }


# Matrices and symbolic questions come before the plain-arithmetic fallback
HANDLERS = [handle_emi, handle_gst, handle_matrix, handle_derivative, handle_integral, handle_plot,
            handle_percent, handle_equation, handle_units, handle_arithmetic]


def answer_question(raw, backend):
    if not isinstance(raw, str) or not raw.strip():
        raise NotUnderstood("Type a question, for example: " + EXAMPLES[0])
    if len(raw) > MAX_QUESTION:
        raise NotUnderstood(f"Keep the question under {MAX_QUESTION} characters")
    question = clean_question(raw)
    for handler in HANDLERS:
        result = handler(question, backend)
        if result is not None:
            result.setdefault("details", [])
            result.setdefault("used", [])
            result.setdefault("notes", [])
            result["question"] = raw.strip()
            return result
    raise NotUnderstood("I couldn't tell what to calculate. Try something like: " + "; ".join(EXAMPLES[:4]))
