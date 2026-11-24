"""Unit tests for math-service: the expression engine, the numerical analysis and every endpoint."""
import math
import sys

import numpy as np
import pytest

from service_loader import load_service, post

module = load_service("math-service")
client = module.app.test_client()
expr = sys.modules["expr"]
analysis = sys.modules["analysis"]


def value_of(text, degrees=False, **env):
    return float(expr.evaluate(expr.parse(text, set(env)), env, degrees))


# ---------------------------------------------------------------- expression engine

@pytest.mark.parametrize("text,expected", [
    ("1 + 2 * 3", 7), ("(1 + 2) * 3", 9), ("2^3^2", 512), ("-2^2", -4), ("2^-1", 0.5),
    ("10 / 4", 2.5), ("7 % 3", 1), ("50%", 0.5), ("200 * 15%", 30), ("5!", 120), ("0!", 1),
    ("2pi", 2 * math.pi), ("3(4 + 1)", 15), ("(1 + 1)(2 + 2)", 8), ("2 sqrt(9)", 6),
    ("sqrt(16) + cbrt(27)", 7), ("root(16, 4)", 2), ("abs(-3.5)", 3.5), ("ln(e^2)", 2), ("log(1000)", 3),
    ("log(8, 2)", 3), ("log2(1024)", 10), ("exp(0)", 1), ("hypot(3, 4)", 5), ("min(4, 2, 8)", 2),
    ("max(4, 2, 8)", 8), ("mod(-7, 3)", 2), ("floor(-2.5)", -3), ("ceil(2.1)", 3), ("round(2.5)", 3),
    ("round(-2.5)", -3), ("nCr(5, 2)", 10), ("nPr(5, 2)", 20), ("10 nCr 3", 120), ("5 nPr 2 + 1", 21),
    ("gamma(5)", 24), ("1e3 + 1", 1001), (".5 + .25", 0.75), ("sinh(0) + cosh(0)", 1), ("phi^2 - phi", 1),
    ("tau / pi", 2), ("2 × 3 ÷ 4 − 1", 0.5), ("π", math.pi), ("√16", 4), ("3²", 9), ("2³", 8),
    ("(2 + 3", 5),   # a missing ")" at the very end is closed automatically
])
def test_evaluate_numbers(text, expected):
    assert math.isclose(value_of(text), expected, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize("text,expected", [("sin(30)", 0.5), ("cos(60)", 0.5), ("tan(45)", 1), ("asin(1)", 90),
                                           ("atan2(1, 1)", 45), ("sec(60)", 2)])
def test_degrees(text, expected):
    assert math.isclose(value_of(text, degrees=True), expected, rel_tol=1e-12)


def test_radians_and_log_ignore_degree_mode():
    assert math.isclose(value_of("sin(pi / 2)"), 1)
    assert value_of("log(100)", degrees=True) == 2        # degrees only affect angle functions


@pytest.mark.parametrize("text,expected", [("xy", "x·y"), ("2x", "2·x"), ("x sin(x)", "x·sin(x)"),
                                           ("pix", "π·x"), ("x^2y", "x^2·y")])
def test_implicit_multiplication(text, expected):
    assert expr.to_text(expr.parse(text, {"x", "y"})) == expected


def test_vectorised_evaluation():
    xs = np.linspace(-2, 2, 5)
    np.testing.assert_allclose(expr.evaluate(expr.parse("x^2 + 1", {"x"}), {"x": xs}), xs ** 2 + 1)


def test_undefined_values_become_nan():
    assert math.isnan(value_of("1 / 0"))
    assert math.isnan(value_of("sqrt(-1)"))
    assert math.isnan(value_of("ln(0 - 5)"))


@pytest.mark.parametrize("text,message", [
    ("", "Enter an expression"),
    ("2 +", "The expression ends too early"),
    ("x2", "Write x^2 for a power, or 2x to multiply"),
    ("foo(2)", "'foo' isn't a known function or constant"),
    ("q + 1", "'q' isn't a variable here. Use x"),
    ("sin", "Put brackets after sin, for example sin(30)"),
    ("nCr", "Write nCr(5, 2) or 5 nCr 2"),
    ("10 nCr", "Put a number after nCr, for example 10 nCr 3"),
    ("log(1, 2, 3)", "log takes 1 to 2 values"),
    ("2 + )", "Something is missing before ')'"),
    ("(1 + 2))", "There's a ')' without a matching '('"),
    ("1 2", None),        # implicit multiplication: allowed, 1·2
    ("2 $ 3", "'$' can't be used in an expression"),
    ("x" * 301, "Keep the expression under 300 characters"),
    ("(" * 45 + "1" + ")" * 45, "The expression has too many nested brackets"),
])
def test_parse_errors(text, message):
    if message is None:
        expr.parse(text, {"x"})
        return
    with pytest.raises(expr.ExpressionError) as err:
        expr.parse(text, {"x"})
    assert str(err.value).startswith(message)


@pytest.mark.parametrize("attack", [
    "__import__('os').system('ls')", "().__class__.__bases__", "open('/etc/passwd')", "lambda: 1",
    "eval('1')", "x.__class__", "[1, 2]", "{'a': 1}", "a; b", "1 if 1 else 2", "exec", "globals()",
])
def test_code_is_never_run(attack):
    """The engine only understands numbers, names it knows and arithmetic: there is no eval()."""
    with pytest.raises(expr.ExpressionError):
        expr.parse(attack, {"x"})


def test_symbolic_text():
    import sympy as sp
    x = sp.Symbol("x", real=True)
    assert expr.sympy_text(sp.diff(expr.to_sympy(expr.parse("x^3 - 3x", {"x"}), {"x": x}), x)) == "3x^2 − 3"
    assert expr.sympy_text(sp.Integer(10) ** 308 * x) == "1×10^(308)·x"


# ---------------------------------------------------------------- numerical analysis

def f_of(text):
    node = expr.parse(text, {"x"})
    return lambda xs: np.broadcast_to(expr.evaluate(node, {"x": np.asarray(xs, dtype=float)}), np.shape(xs))


def test_roots():
    roots, more = analysis.find_roots(f_of("x^2 - 2"), -5, 5)
    np.testing.assert_allclose(roots, [-math.sqrt(2), math.sqrt(2)], rtol=1e-10)
    roots, _ = analysis.find_roots(f_of("sin(x)"), -7, 7)
    np.testing.assert_allclose(roots, [-2 * math.pi, -math.pi, 0, math.pi, 2 * math.pi], atol=1e-9)
    roots, _ = analysis.find_roots(f_of("(x - 1)^2"), -3, 3)          # touches zero without crossing
    np.testing.assert_allclose(roots, [1], atol=1e-6)
    assert analysis.find_roots(f_of("1/x"), -3, 3)[0] == []           # a pole is not a root
    assert analysis.find_roots(f_of("tan(x)"), 1, 2)[0] == []         # nor is tan's jump at π/2


def test_turning_points_are_rounded_sensibly():
    xs = np.linspace(-4, 4, 600)
    f = f_of("x^2/8 - 2")
    assert analysis.find_extrema(f, xs, f(xs))[0] == [{"x": 0.0, "y": -2.0, "kind": "min"}]
    f = f_of("x^3 - 3x")
    points, _ = analysis.find_extrema(f, xs, f(xs))
    assert [(p["x"], p["y"], p["kind"]) for p in points] == [(-1.0, 2.0, "max"), (1.0, -2.0, "min")]


def test_integral_and_area():
    integral, area = analysis.integrate(f_of("sin(x)"), 0, math.pi)
    assert math.isclose(integral, 2, rel_tol=1e-10) and math.isclose(area, 2, rel_tol=1e-10)
    f = f_of("x^3 - 3x")
    roots, _ = analysis.find_roots(f, -2, 2)
    integral, area = analysis.integrate(f, -2, 2, breaks=roots)
    assert integral == 0 and math.isclose(area, 5, rel_tol=1e-9)
    assert analysis.integrate(f_of("x^2"), 3, 0)[0] == pytest.approx(-9)    # limits swapped: negative
    assert analysis.integrate(f_of("1/x"), -1, 1) is None                   # undefined at 0


def test_describe():
    d = analysis.describe([2, 4, 4, 4, 5, 5, 7, 9], sample=False)
    assert d["mean"] == 5 and d["median"] == 4.5 and d["std"] == 2 and d["modes"] == [4]
    d = analysis.describe(list(range(1, 11)) + [100], sample=True)
    assert d["outliers"] == [100] and d["q1"] == 3.5 and d["q3"] == 8.5


def test_regression():
    r = analysis.regression([1, 2, 3, 4], [3, 5, 7, 9])
    assert (r["slope"], r["intercept"], r["r"], r["r2"]) == (2, 1, 1, 1)


# ---------------------------------------------------------------- endpoints

def test_health_ready_and_cache_down():
    assert client.get("/health").get_json()["service"] == "math-service"
    ready = client.get("/ready")
    assert ready.status_code == 200                  # the cache is optional: math-service works without it
    assert ready.get_json()["cache"] != "connected"


def test_functions_catalogue():
    names = {f["name"] for f in client.get("/functions").get_json()["functions"]}
    assert {"sin", "ln", "sqrt", "nCr", "gamma"} <= names


def test_evaluate_endpoint():
    b = post(client, "/evaluate", {"expression": "sin(30) + 2^10 + sqrt(16)"})
    assert b["result"] == 1028.5 and b["angle"] == "deg" and b["uses_angles"] is True
    assert b["interpreted"] == "sin(30) + 2^10 + sqrt(16)" and b["saved"] is False
    assert post(client, "/evaluate", {"expression": "ans / 2", "ans": 1028.5})["result"] == 514.25
    assert post(client, "/evaluate", {"expression": "0.1 + 0.2"})["result"] == 0.3


@pytest.mark.parametrize("body,message", [
    ({"expression": "1/0"}, "The answer is undefined"),
    ({"expression": "10^400"}, "The answer is infinite or too large to show"),
    ({"expression": "ans + 1"}, "There's no previous answer yet"),
    ({"expression": "2 +"}, "The expression ends too early"),
    ({"expression": "1", "angle": "grad"}, "Angle unit must be one of"),
])
def test_evaluate_errors(body, message):
    b = post(client, "/evaluate", body, 400)
    assert b["error"].startswith(message)


def test_plot2d():
    b = post(client, "/plot2d", {"functions": ["sin(x)", "", "x^2 - 4"], "x_min": -5, "x_max": 5, "points": 400})
    assert len(b["x"]) == 400 and len(b["series"]) == 2 and b["cached"] is False
    np.testing.assert_allclose(b["series"][0]["roots"], [-math.pi, 0, math.pi], atol=1e-5)
    assert b["series"][1]["roots"] == [-2, 2] and b["series"][1]["y_intercept"] == -4
    assert post(client, "/plot2d", {"functions": ["1/x"], "x_min": -1, "x_max": 1})["series"][0]["roots"] == []


@pytest.mark.parametrize("body,field", [
    ({"functions": ["sin(x)", "x +"]}, "f1"),
    ({"functions": []}, "f0"),
    ({"functions": ["x"] * 5}, "functions"),
    ({"functions": ["x"], "x_min": 5, "x_max": 1}, "x_max"),
])
def test_plot2d_errors(body, field):
    assert post(client, "/plot2d", body, 400)["field"] == field


def test_plot2d_from_history_is_not_saved_again():
    assert post(client, "/plot2d", {"functions": ["x"], "history": False})["saved"] is None


def test_plot3d_modes():
    s = post(client, "/plot3d", {"mode": "surface", "expression": "x^2 - y^2", "x_min": -2, "x_max": 2,
                                 "y_min": -2, "y_max": 2, "resolution": 31})
    assert len(s["z"]) == 31 and len(s["z"][0]) == 31 and s["z_min"] == -4 and s["z_max"] == 4
    c = post(client, "/plot3d", {"mode": "curve", "expr_x": "cos(t)", "expr_y": "sin(t)", "expr_z": "t",
                                 "t_min": 0, "t_max": 10, "points": 100})
    assert len(c["x"]) == len(c["t"]) == 100
    p = post(client, "/plot3d", {"mode": "parametric", "expr_x": "cos(u)sin(v)", "expr_y": "sin(u)sin(v)",
                                 "expr_z": "cos(v)", "u_min": 0, "u_max": 6.3, "v_min": 0, "v_max": 3.15,
                                 "resolution": 20})
    assert len(p["x"]) == 20 and max(max(row) for row in p["z"]) == pytest.approx(1, abs=0.01)


def test_plot3d_errors():
    b = post(client, "/plot3d", {"mode": "surface", "expression": "sqrt(-1 - x^2 - y^2)"}, 400)
    assert b["error"] == "z has no real values anywhere in this x and y range"
    assert post(client, "/plot3d", {"mode": "curve", "expr_x": "u", "expr_y": "t", "expr_z": "t"}, 400)["field"] == "expr_x"
    assert post(client, "/plot3d", {"mode": "surface", "expression": "x", "resolution": 500}, 400)["field"] == "resolution"


def test_calculus():
    b = post(client, "/calculus", {"expression": "x^3 - 3x", "x0": 2, "a": -2, "b": 2})
    assert b["derivative"]["text"] == "3x^2 − 3" and b["derivative"]["second_text"] == "6x"
    assert b["derivative"]["value"] == 9 and b["derivative"]["exact"] is True
    assert b["tangent"]["text"] == "y = 9x − 16"
    assert b["integral"]["value"] == 0 and b["integral"]["area"] == 5
    assert [round(r, 6) for r in b["roots"]] == [-1.732051, 0, 1.732051]


def test_calculus_numeric_fallback_and_errors():
    b = post(client, "/calculus", {"expression": "round(x) * x", "x0": 0.3, "a": 0, "b": 1})
    assert b["derivative"]["text"] is None and b["derivative"]["exact"] is False
    assert post(client, "/calculus", {"expression": "ln(x)", "x0": -1, "a": 1, "b": 2}, 400)["field"] == "x0"
    assert post(client, "/calculus", {"expression": "x", "x0": 1, "a": 2, "b": 2}, 400)["field"] == "b"
    undefined = post(client, "/calculus", {"expression": "1/x", "x0": 1, "a": -1, "b": 1})["integral"]
    assert undefined["defined"] is False


def test_statistics():
    b = post(client, "/statistics", {"x": "2, 4, 4, 4, 5, 5, 7, 9", "mode": "population"})
    assert b["mean"] == 5 and b["std"] == 2 and b["count"] == 8 and b["regression"] is None
    b = post(client, "/statistics", {"x": [1, 2, 3, 4], "y": "3 5 7 9"})
    assert b["regression"]["equation"] == "y = 2x + 1" and b["regression"]["r"] == 1


@pytest.mark.parametrize("body,message", [
    ({"x": ""}, "Enter some values"),
    ({"x": "1, two, 3"}, "'two' isn't a number"),
    ({"x": "1 2 3", "y": "1 2"}, "Enter the same number of y values as x values (3 x, 2 y)"),
    ({"x": "5 5 5", "y": "1 2 3"}, "For a line of best fit, the x values can't all be the same"),
    ({"x": " ".join(["1"] * 5001)}, "Enter at most 5,000 values"),
])
def test_statistics_errors(body, message):
    assert post(client, "/statistics", body, 400)["error"].startswith(message)


@pytest.mark.parametrize("shape,dims,volume", [
    ("cube", {"a": 3}, 27), ("cuboid", {"l": 8, "w": 5, "h": 4}, 160), ("cylinder", {"r": 3, "h": 10}, 90 * math.pi),
    ("cone", {"r": 3, "h": 7}, 21 * math.pi), ("sphere", {"r": 3}, 36 * math.pi), ("hemisphere", {"r": 3}, 18 * math.pi),
    ("frustum", {"R": 6, "r": 3, "h": 8}, 168 * math.pi), ("pyramid", {"a": 6, "h": 8}, 96),
    ("torus", {"R": 5, "r": 1.5}, 2 * math.pi ** 2 * 5 * 1.5 ** 2),
])
def test_solid_volumes(shape, dims, volume):
    b = post(client, "/solid", {"shape": shape, "dims": dims, "unit": "cm"})
    assert math.isclose(next(r["value"] for r in b["results"] if r["kind"] == "volume"), volume, rel_tol=1e-9)
    assert math.isclose(b["litres"], volume / 1000, rel_tol=1e-9)        # 1 litre = 1000 cm³


def test_solid_errors():
    assert post(client, "/solid", {"shape": "cube", "dims": {"a": -1}}, 400)["field"] == "a"
    assert post(client, "/solid", {"shape": "torus", "dims": {"R": 1, "r": 2}}, 400)["field"] == "r"
    assert post(client, "/solid", {"shape": "blob", "dims": {}}, 400)["field"] == "shape"
    catalogue = client.get("/solids").get_json()
    assert len(catalogue["shapes"]) == 9 and "cm" in catalogue["units"]


def test_metrics_include_cache_lookups():
    post(client, "/plot2d", {"functions": ["x^3"]})
    text = client.get("/metrics").get_data(as_text=True)
    assert 'http_requests_total{endpoint="/plot2d",method="POST",service="math-service",status="200"}' in text
    assert "cache_requests_total" in text
