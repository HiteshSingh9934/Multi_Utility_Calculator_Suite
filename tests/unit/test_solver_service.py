"""solver-service: worked solutions and plain-English questions.

The other services are real here (their Flask apps run in this process), reached through a stand-in for
the network, so /ask is tested end to end without Docker.
"""
import re
from pathlib import Path

import pytest
import sympy as sp

from service_loader import SERVICES, load_service, post

solver = load_service("solver-service")
asking = solver.asking
calculus_steps, algebra_steps, finance_steps, expr = asking.calculus_steps, asking.algebra_steps, asking.finance_steps, asking.expr
SIBLINGS = {key: load_service(f"{key}-service") for key in ("calc", "converter", "finance", "math")}
X = sp.Symbol("x")


class Network:
    """Sends solver-service's calls to the real Flask apps of the other services."""

    def __init__(self, down=()):
        self.down = set(down)
        self.calls = []

    def call(self, key, path, payload=None, method="POST"):
        self.calls.append((key, path))
        if key in self.down:
            raise asking.ServiceProblem(f"{key}-service", f"{key}-service isn't answering right now")
        client = SIBLINGS[key].app.test_client()
        response = client.get(path) if method == "GET" else client.post(path, json=payload)
        body = response.get_json() or {}
        if response.status_code >= 500:
            raise asking.ServiceProblem(f"{key}-service", "down", response.status_code)
        if response.status_code >= 400:
            raise calculus_steps.Unsupported(body.get("error", "refused"))
        return body, body.get("served_by")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(solver, "BACKEND", Network())
    asking._units_cache.update(at=0.0, words=None)
    return solver.app.test_client()


def sym(text):
    return expr.to_sympy(expr.parse(text, ("x",)), {"x": X})


def test_expr_is_the_same_safe_parser_as_math_service():
    mine = (SERVICES / "solver-service" / "expr.py").read_bytes()
    assert mine == (SERVICES / "math-service" / "expr.py").read_bytes(), "copy math-service/expr.py again"


# ---------------------------------------------------------------------------
# Derivatives: every answer must equal SymPy's, and the working must name the rule used
# ---------------------------------------------------------------------------

DERIVATIVES = [
    ("x^3 - 2x + 7", "Power rule"), ("x^2 sin(x)", "Product rule"), ("(x^2+1)/(x-3)", "Quotient rule"),
    ("sin(3x+1)", "Chain rule"), ("e^(2x) ln(x)", "Product rule"), ("x^x", "Logarithmic differentiation"),
    ("sqrt(x) + 1/x", "Sum rule"), ("5", "Constant rule"), ("tan(x)/x", "Quotient rule"),
    ("cos(x^2)", "Chain rule"), ("2^x", "Exponential rule"), ("atan(x)", "Standard derivative"),
    ("sin(x)^2", "Power rule with the chain rule"), ("3x", "Constant multiple rule"),
]


@pytest.mark.parametrize("text,rule", DERIVATIVES)
def test_derivative_matches_sympy_and_names_the_rule(text, rule):
    f = sym(text)
    answer, steps = calculus_steps.differentiate(f, X)
    assert calculus_steps.agree(answer, sp.diff(f, X), X)
    assert rule in [step["rule"] for step in steps]
    assert all(step["text"] for step in steps)


def test_derivative_at_a_point():
    answer, steps = calculus_steps.differentiate(sym("x^3 - 2x"), X, sp.Integer(2))
    assert steps[-1]["rule"] == "Evaluate" and "f'(2) = 10" in steps[-1]["math"]


def test_derivative_at_a_point_where_it_does_not_exist():
    with pytest.raises(calculus_steps.Unsupported):
        calculus_steps.differentiate(sym("1/x"), X, sp.Integer(0))


# ---------------------------------------------------------------------------
# Integrals: the antiderivative must differentiate back, and improper integrals are refused
# ---------------------------------------------------------------------------

INTEGRALS = ["x^2", "x^2 sin(x)", "sin(3x+1)", "e^x x", "2x/(x^2+1)", "1/(1+x^2)", "sin(x)^2", "x^3 - 2x + 1", "ln(x)", "sqrt(x)"]


@pytest.mark.parametrize("text", INTEGRALS)
def test_indefinite_integral_differentiates_back(text):
    f = sym(text)
    answer, number, steps = calculus_steps.integrate(f, X)
    assert answer.endswith("+ C") and number is None and steps
    assert steps[-1]["rule"] == "Add the constant"


@pytest.mark.parametrize("text,lower,upper,expected", [
    ("x^2", 0, 3, 9.0), ("x^3 - 2x", 1, 4, 48.75), ("1/(1+x^2)", 0, 1, 0.7853981633974483),
    ("sin(x)", 0, sp.pi, 2.0), ("e^x", 0, 1, 1.718281828459045),
])
def test_definite_integral_values(text, lower, upper, expected):
    answer, number, steps = calculus_steps.integrate(sym(text), X, sp.sympify(lower), sp.sympify(upper))
    assert number == pytest.approx(expected)
    assert "Fundamental theorem of calculus" in [step["rule"] for step in steps]


@pytest.mark.parametrize("text,lower,upper", [("1/x^2", -1, 1), ("1/x", -1, 2), ("tan(x)", 0, 2), ("sqrt(x)", -1, 4)])
def test_improper_integrals_are_refused_not_miscalculated(text, lower, upper):
    with pytest.raises(calculus_steps.Unsupported):
        calculus_steps.integrate(sym(text), X, sp.Integer(lower), sp.Integer(upper))


def test_integral_that_needs_the_error_function_is_still_answered():
    answer, number, steps = calculus_steps.integrate(sym("e^(-x^2)"), X)
    assert "erf" in answer and steps


# ---------------------------------------------------------------------------
# Equations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("left,right,roots", [
    ("x^2 - 5x + 6", "0", {2, 3}), ("2x + 3", "11", {4}), ("x^2 - 4x + 4", "0", {2}), ("x^2", "2", {sp.sqrt(2), -sp.sqrt(2)}),
    ("x^3 - 6x^2 + 11x - 6", "0", {1, 2, 3}), ("x^2", "-x^2", {0}), ("3x - 2", "x + 4", {3}),
])
def test_equation_roots(left, right, roots):
    solutions, steps = algebra_steps.solve_equation(sym(left), sym(right), X)
    assert {sp.simplify(s) for s in solutions} == {sp.simplify(r) for r in roots}
    assert steps[-1]["rule"] == "Check"


def test_quadratic_without_real_roots_gives_complex_ones():
    solutions, steps = algebra_steps.solve_equation(sym("x^2 + x + 1"), sp.Integer(0), X)
    assert len(solutions) == 2 and all(not s.is_real for s in solutions)
    assert any("complex" in step["text"] for step in steps)


@pytest.mark.parametrize("left,right", [("x + 1", "x + 2"), ("x + 1", "x + 1")])
def test_equations_with_no_or_every_solution_are_explained(left, right):
    with pytest.raises(calculus_steps.Unsupported):
        algebra_steps.solve_equation(sym(left), sym(right), X)


# ---------------------------------------------------------------------------
# Matrices: checked against SymPy
# ---------------------------------------------------------------------------

MATRICES = [[[2, 1], [5, 3]], [[2, 1, 3], [0, -1, 4], [1, 2, 5]], [[1, 2, 3, 4], [0, 1, 4, 5], [5, 6, 0, 7], [1, 0, 3, 2]],
            [["1/2", 3], [4, 5]]]


@pytest.mark.parametrize("rows", MATRICES)
def test_determinant_matches_sympy(rows):
    value, steps = algebra_steps.determinant_steps(rows)
    expected = sp.Matrix([[sp.Rational(str(c)) for c in r] for r in rows]).det()
    assert sp.Rational(value.numerator, value.denominator) == expected
    assert steps


@pytest.mark.parametrize("rows", [[[2, 1], [5, 3]], [[2, 1, 3], [0, -1, 4], [1, 2, 5]], [[4, 7], [2, 6]]])
def test_inverse_matches_sympy(rows):
    inverse, steps = algebra_steps.inverse_steps(rows)
    expected = sp.Matrix(rows).inv()
    got = sp.Matrix([[sp.Rational(c.replace("−", "-")) for c in row] for row in inverse["rows"]])
    assert got == expected
    assert steps[-1]["matrix"]["rows"] == inverse["rows"]


def test_singular_matrix_has_no_inverse():
    inverse, steps = algebra_steps.inverse_steps([[1, 2], [2, 4]])
    assert inverse is None and steps[-1]["rule"] == "No inverse"


def test_solving_a_system():
    solution, steps = algebra_steps.solve_steps([[2, 1, -1], [-3, -1, 2], [-2, 1, 2]], [8, -11, -3])
    assert [str(v) for v in solution] == ["2", "3", "-1"]


@pytest.mark.parametrize("rows,constants,rule", [([[1, 1], [2, 2]], [1, 3], "No solution"), ([[1, 1], [2, 2]], [1, 2], "Infinitely many solutions")])
def test_systems_without_one_answer(rows, constants, rule):
    solution, steps = algebra_steps.solve_steps(rows, constants)
    assert solution is None and steps[-1]["rule"] == rule


def test_rref_rank():
    reduced, steps, info = algebra_steps.rref_steps([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    assert info["rank"] == 2 and reduced["rows"][2] == ["0", "0", "0"]


@pytest.mark.parametrize("bad", [[], [[]], [[1, 2], [3]], [[1, "x"]], "nope", [[1] * 7] * 7])
def test_bad_matrices_are_explained(bad):
    with pytest.raises(calculus_steps.Unsupported):
        algebra_steps.parse_matrix(bad)


def test_matrix_text_forms():
    assert algebra_steps.matrix_from_text("1 2; 3 4") == [["1", "2"], ["3", "4"]]
    assert algebra_steps.matrix_from_text("[[1,2],[3,4]]") == [[1, 2], [3, 4]]
    assert algebra_steps.matrix_from_text("1/2, 3 ; 4, 5") == [["1/2", "3"], ["4", "5"]]


# ---------------------------------------------------------------------------
# EMI and GST: the worked figures must equal finance-service's
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("principal,rate,months", [(500000, 9, 36), (250000, 10.5, 18), (1000000, 7.25, 240), (80000, 0, 12), (1234567, 12, 7)])
def test_emi_steps_agree_with_finance_service(principal, rate, months):
    numbers, steps = finance_steps.emi_steps(principal, rate, months)
    reply = post(SIBLINGS["finance"].app.test_client(), "/emi", {"principal": principal, "annual_rate": rate, "tenure": months, "tenure_unit": "months"})
    assert numbers["emi"] == pytest.approx(reply["emi"], abs=0.011)
    assert numbers["total_interest"] == pytest.approx(reply["total_interest"], abs=1.0)
    assert len(steps) >= 5


@pytest.mark.parametrize("amount,rate,mode", [(2499, 18, "exclusive"), (1180, 18, "inclusive"), (100, 5, "exclusive"), (999.99, 12, "inclusive")])
def test_gst_steps_agree_with_finance_service(amount, rate, mode):
    numbers, steps = finance_steps.gst_steps(amount, rate, mode)
    reply = post(SIBLINGS["finance"].app.test_client(), "/gst", {"amount": amount, "rate": rate, "mode": mode})
    assert numbers["gst"] == pytest.approx(reply["gst_amount"], abs=0.011)
    assert numbers["gross"] == pytest.approx(reply["gross_amount"], abs=0.011)


@pytest.mark.parametrize("value,shown", [(1234567.5, "₹12,34,567.50"), (999, "₹999.00"), (100000, "₹1,00,000.00"), (-2500.5, "−₹2,500.50")])
def test_rupee_grouping(value, shown):
    assert finance_steps.inr(value) == shown


# ---------------------------------------------------------------------------
# /ask: plain English in, an answer and working out
# ---------------------------------------------------------------------------

def ask(client, text, status=200):
    return post(client, "/ask", {"text": text}, status)


def test_ask_emi_uses_finance_service_and_shows_the_working(client):
    reply = ask(client, "EMI for 5 lakh at 9% for 3 years")
    assert reply["intent"] == "emi" and reply["answer"] == "₹15,899.87 a month"
    assert reply["understood"] == "EMI on ₹5,00,000 at 9% a year for 3 years"
    assert [u["service"] for u in reply["used"]] == ["solver-service", "finance-service"]
    assert len(reply["steps"]) >= 6
    assert reply["open"] == {"tool": "emi", "fields": {"emi-principal": 500000.0, "emi-rate": 9.0, "emi-tenure": 3.0},
                             "choices": {"tenure_unit": "years"}}


@pytest.mark.parametrize("text,emi", [
    ("what is the emi on a loan of ₹2,50,000 at 10.5% pa for 18 months", "₹15,071.89"),
    ("loan 10L 8.5 percent 20 years emi", "₹8,678.23"),
    ("Home loan of 1 crore at 7.5% for 25 yrs", "₹73,899.12"),
    ("emi of 50k at 12% for 6 months", "₹8,627.42"),
])
def test_ask_emi_in_different_words(client, text, emi):
    assert ask(client, text)["answer"].startswith(emi)


@pytest.mark.parametrize("text,missing", [("emi for 5 lakh", "interest rate"), ("emi at 9% for 3 years", "loan amount"), ("loan of 5 lakh at 9%", "time")])
def test_ask_emi_says_what_is_missing(client, text, missing):
    reply = ask(client, text, 422)
    assert reply["code"] == "not_understood" and missing in reply["error"]


def test_ask_still_answers_when_finance_service_is_down(client, monkeypatch):
    monkeypatch.setattr(solver, "BACKEND", Network(down=["finance"]))
    reply = ask(client, "EMI for 5 lakh at 9% for 3 years")
    assert reply["answer"] == "₹15,899.87 a month" and reply["steps"]
    assert any("finance-service isn't answering" in note for note in reply["notes"])
    assert [u["service"] for u in reply["used"]] == ["solver-service"]


def test_ask_gst(client):
    exclusive = ask(client, "18% GST on 2499")
    assert exclusive["intent"] == "gst" and exclusive["answer"] == "₹2,948.82 in total"
    inclusive = ask(client, "gst inclusive 1180 at 18%")
    assert inclusive["answer"] == "₹1,000.00 before GST"
    assumed = ask(client, "add gst to 1000")
    assert assumed["answer"] == "₹1,180.00 in total" and any("18%" in n for n in assumed["notes"])


@pytest.mark.parametrize("text,answer", [
    ("convert 72 f to c", "72 °F = 22.22222222 °C"), ("5 km to miles", "5 km = 3.106855961 mi"),
    ("10 kg in pounds", "10 kg = 22.04622622 lb"), ("3 hours to minutes", "3 h = 180 min"), ("100 cm to inches", "100 cm = 39.37007874 in"),
])
def test_ask_unit_conversion(client, text, answer):
    reply = ask(client, text)
    assert reply["intent"] == "unit-converter" and reply["answer"] == answer
    assert reply["used"][1]["service"] == "converter-service"


def test_ask_refuses_to_mix_unlike_units(client):
    reply = ask(client, "5 kg to km", 422)
    assert "different things" in reply["error"]


def test_ask_conversion_needs_converter_service(client, monkeypatch):
    monkeypatch.setattr(solver, "BACKEND", Network(down=["converter"]))
    reply = ask(client, "5 km to miles", 503)
    assert reply["code"] == "service_unavailable" and reply["service"] == "converter-service"


def test_ask_calculus(client):
    d = ask(client, "derivative of x^2 sin(x)")
    assert d["intent"] == "derivative" and d["answer"].startswith("d/dx [x^2·sin(x)] = ") and "cos(x)" in d["answer"]
    at = ask(client, "differentiate x^3 - 2x at x = 2")
    assert at["details"][0]["value"] == "10"
    i = ask(client, "integrate x e^x from 0 to 2")
    assert i["answer"].endswith("= 1 + e^2") and i["details"][0]["value"] == "8.3890561"
    assert ask(client, "∫ x^2 dx")["answer"] == "∫ x^2 dx = x^3/3 + C"
    assert ask(client, "d/dx sin(x)^2")["intent"] == "derivative"


def test_ask_equations(client):
    assert ask(client, "solve x^2 - 5x + 6 = 0")["answer"] == "x = 2 and x = 3"
    assert ask(client, "2x + 3 = 11")["answer"] == "x = 4"
    assert ask(client, "roots of x^2 - 2")["details"][0]["label"] == "As decimals"


def test_ask_matrices(client):
    det = ask(client, "determinant of [[2,1],[5,3]]")
    assert det["answer"] == "det = 1"
    inverse = ask(client, "inverse of 2 1; 5 3")
    assert inverse["matrix"] == {"rows": [["3", "−1"], ["−5", "2"]], "split": None}
    assert ask(client, "rref of [[1,2],[2,4]]")["answer"].endswith("rank 1")
    assert "singular" in ask(client, "inverse of [[1,2],[2,4]]")["answer"]
    assert ask(client, "determinant", 422)["code"] == "not_understood"


def test_ask_plots_hand_over_to_the_graph_tools(client):
    flat = ask(client, "plot sin(x)")
    assert flat["open"]["tool"] == "plotter" and flat["hands_over"] and "steps" not in flat
    surface = ask(client, "graph x^2 + y^2")
    assert surface["open"]["tool"] == "graph3d" and surface["open"]["fields"] == {"g3-z": "x^2 + y^2"}
    assert ask(client, "plot 3d sin(x)*cos(y)")["open"]["tool"] == "graph3d"


@pytest.mark.parametrize("text,answer", [
    ("20% of 350", "20% of 350 = 70"), ("sqrt(144) + 3^2", "sqrt(144) + 3^2 = 21"),
    ("12 plus 30 times 2", "12 + 30·2 = 72"), ("what is 7 squared", "7^2 = 49"),
])
def test_ask_plain_arithmetic(client, text, answer):
    assert ask(client, text)["answer"] == answer


@pytest.mark.parametrize("text", ["hello there", "tell me a joke", "5 apples to oranges", "", "   ", "?"])
def test_ask_gives_examples_when_it_cannot_tell(client, text):
    reply = ask(client, text, 422)
    assert reply["code"] == "not_understood" and reply["examples"]


def test_ask_rejects_bad_requests(client):
    assert client.post("/ask", json={"text": 5}).status_code == 400
    assert client.post("/ask", data="x", content_type="text/plain").status_code == 400
    assert ask(client, "x" * 400, 422)["code"] == "not_understood"


@pytest.mark.parametrize("attack", ["derivative of __import__('os').system('id')", "integrate open('/etc/passwd')", "solve x = exec('1')"])
def test_ask_never_runs_code(client, attack):
    response = client.post("/ask", json={"text": attack})
    assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# The direct endpoints, history and monitoring
# ---------------------------------------------------------------------------

def test_direct_endpoints(client):
    d = post(client, "/derivative", {"expression": "x^3 - 2x", "at": 2})
    assert d["details"][0]["value"] == "10" and d["steps"]
    i = post(client, "/integral", {"expression": "x^2", "lower": 0, "upper": 3})
    assert i["answer"].endswith("= 9") and i["details"][0]["value"] == "9"
    assert post(client, "/equation", {"equation": "x^2 = 9"})["answer"] == "x = −3 and x = 3"
    m = post(client, "/matrix-steps", {"operation": "determinant", "matrix": [[1, 2], [3, 4]]})
    assert m["answer"] == "det = −2"
    s = post(client, "/matrix-steps", {"operation": "solve", "matrix": [[1, 1], [1, -1]], "constants": [10, 2]})
    assert s["answer"] == "x = 6,  y = 4"
    e = post(client, "/emi-steps", {"principal": 500000, "annual_rate": 9, "tenure": 3})
    assert e["answer"] == "₹15,899.87 a month"
    g = post(client, "/gst-steps", {"amount": 1000, "rate": 5})
    assert g["answer"] == "₹1,050.00 in total"


def test_direct_endpoints_validate_input(client):
    post(client, "/derivative", {"expression": ""}, 400)
    post(client, "/integral", {"expression": "x", "lower": 0}, 422)
    post(client, "/matrix-steps", {"operation": "explode", "matrix": [[1]]}, 400)
    post(client, "/matrix-steps", {"operation": "determinant", "matrix": [[1, 2]]}, 422)
    post(client, "/emi-steps", {"principal": -5, "annual_rate": 9, "tenure": 3}, 400)
    post(client, "/gst-steps", {"amount": 10, "rate": 5, "mode": "sideways"}, 400)
    post(client, "/equation", {"equation": "x + 1 = x + 2"}, 422)


def test_solutions_are_saved_to_history_under_the_solver_tool(client, monkeypatch):
    saved = []
    monkeypatch.setattr(solver, "save_history", lambda tool, summary, inputs, result: saved.append((tool, summary, inputs)) or True)
    reply = ask(client, "solve x^2 - 5x + 6 = 0")
    assert reply["saved"] is True
    assert saved[0][0] == "solver" and "x = 2 and x = 3" in saved[0][1] and saved[0][2]["kind"] == "equation"
    assert re.search("solver", Path(SERVICES / "history-service" / "app.py").read_text())


def test_health_and_metrics(client):
    health = client.get("/health").get_json()
    assert health["service"] == "solver-service" and health["status"] == "ok"
    ask(client, "2x + 3 = 11")
    assert 'endpoint="/ask"' in client.get("/metrics").get_data(as_text=True)
    assert client.get("/examples").get_json()["examples"]


def test_no_history_warning_when_there_is_nothing_to_save(client, monkeypatch):
    """EMI and GST steps are saved by the finance tool, so the solver reports saved=None, not saved=False."""
    monkeypatch.setattr(solver, "save_history", lambda *args: False)
    reply = client.post("/gst-steps", json={"amount": "2499", "rate": "18", "mode": "exclusive"}).get_json()
    assert reply["saved"] is None
