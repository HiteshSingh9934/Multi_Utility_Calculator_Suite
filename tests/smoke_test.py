"""End-to-end smoke test: calls every tool through the gateway, the way the web page does.

Run it inside Docker (no Python needed on your computer):
    docker compose run --rm smoke-test

Or with Python on your computer:
    python tests/smoke_test.py http://localhost:8080          (Docker Compose)
    python tests/smoke_test.py http://localhost:30080         (Kubernetes)
"""
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")
failures = 0


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.headers.get("Content-Encoding") == "gzip":
                return response.status, response.headers
            text = response.read().decode()
            return response.status, (json.loads(text) if text.startswith(("{", "[")) else text)
    except urllib.error.HTTPError as err:
        text = err.read().decode()
        try:
            return err.code, json.loads(text)
        except ValueError:
            return err.code, text
    except (urllib.error.URLError, OSError) as err:
        return 0, {"error": str(err)}


def check(name, passed, detail=""):
    global failures
    if not passed:
        failures += 1
    print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not passed else ""))


def close(a, b, tolerance=0.01):
    return isinstance(a, (int, float)) and abs(a - b) <= tolerance


print(f"Smoke test against {BASE}\n")

print("Gateway and services")
status, _ = call("GET", "/healthz")
check("gateway answers /healthz", status == 200, f"HTTP {status}")
for name, path in [("calc-service", "/api/calc/health"), ("converter-service", "/api/converter/health"),
                   ("finance-service", "/api/finance/health"), ("student-service", "/api/student/health"),
                   ("math-service", "/api/math/health"), ("matrix-service", "/api/matrix/health"), ("solver-service", "/api/solver/health"),
                   ("history-service + database", "/api/history/ready")]:
    status, body = call("GET", path)
    check(f"{name} is healthy", status == 200, f"HTTP {status}: {body}")
status, body = call("GET", "/api/math/ready")
check("math-service is connected to the Redis cache", status == 200 and body.get("cache") == "connected", body)
status, headers = call("GET", "/vendor/plotly.min.js", headers={"Accept-Encoding": "gzip"})
check("the chart library is served compressed", status == 200 and headers.get("Content-Encoding") == "gzip",
      f"HTTP {status}")
status, body = call("GET", "/api/math/metrics")
check("services' /metrics pages are not public (gateway answers 404)", status == 404, f"HTTP {status}")

print("\nTools")
status, body = call("POST", "/api/calc/calculate", {"num1": 12, "num2": 4, "operation": "multiply"})
check("calculator: 12 x 4 = 48", status == 200 and body.get("result") == 48, body)

status, body = call("POST", "/api/calc/calculate", {"num1": 1, "num2": 0, "operation": "divide"})
check("calculator: dividing by zero is rejected", status == 400, body)

status, body = call("POST", "/api/converter/convert",
                    {"category": "length", "value": 10, "from_unit": "km", "to_unit": "mi"})
check("unit converter: 10 km = 6.2137 mi", status == 200 and close(body.get("result"), 6.2137, 0.0001), body)

status, body = call("POST", "/api/converter/convert",
                    {"category": "temperature", "value": 100, "from_unit": "c", "to_unit": "f"})
check("unit converter: 100 C = 212 F", status == 200 and body.get("result") == 212, body)

status, body = call("POST", "/api/finance/gst",
                    {"amount": 1000, "rate": 18, "mode": "exclusive", "supply": "intra"})
check("GST: 18% on 1,000 = 1,180 (CGST 90 + SGST 90)",
      status == 200 and body.get("gross_amount") == 1180
      and [b["amount"] for b in body.get("breakdown", [])] == [90, 90], body)

status, body = call("POST", "/api/finance/emi",
                    {"principal": 500000, "annual_rate": 9, "tenure": 5, "tenure_unit": "years"})
check("EMI: 5,00,000 at 9% for 5 years is about 10,379 a month",
      status == 200 and close(body.get("emi"), 10379.18, 0.5), body)

status, body = call("POST", "/api/student/cgpa", {"direction": "to_percentage", "value": 8.2, "formula": "mitadt"})
check("CGPA: 8.2 x 9.56 = 78.39%", status == 200 and body.get("result") == 78.39, body)

status, body = call("POST", "/api/student/grades", {"subjects": [
    {"name": "Maths", "marks": 92, "credits": 4}, {"name": "Physics", "marks": 78, "credits": 3}]})
check("grades: 85% overall, grade A+, SGPA 9.14",
      status == 200 and body.get("percentage") == 85 and body.get("overall_grade") == "A+"
      and body.get("sgpa") == 9.14, body)

status, body = call("POST", "/api/student/attendance", {"attended": 42, "total": 60, "required": 75})
check("attendance: 42/60 needs 12 more classes for 75%", status == 200 and body.get("must_attend") == 12, body)

print("\nMaths, graphs and 3D (math-service)")
status, body = call("POST", "/api/math/evaluate", {"expression": "sin(30) + 2^10 + sqrt(16)", "angle": "deg"})
check("scientific: sin(30 deg) + 2^10 + sqrt(16) = 1028.5", status == 200 and body.get("result") == 1028.5, body)

status, body = call("POST", "/api/math/plot2d", {"functions": ["x^2 - 4"], "x_min": -5, "x_max": 5})
roots = body.get("series", [{}])[0].get("roots") if status == 200 else None
check("function plotter: x^2 - 4 crosses zero at -2 and 2", roots == [-2, 2], body if status != 200 else roots)

surface = {"mode": "surface", "expression": "sin(sqrt(x^2 + y^2))", "x_min": -6, "x_max": 6,
           "y_min": -6, "y_max": 6, "resolution": 40}
status, body = call("POST", "/api/math/plot3d", surface)
check("3D graph: a 40 x 40 surface", status == 200 and len(body.get("z", [])) == 40, body if status != 200 else "")
status, body = call("POST", "/api/math/plot3d", surface)
check("3D graph: the same graph again comes from the Redis cache", status == 200 and body.get("cached") is True,
      f"cached = {body.get('cached') if status == 200 else body}")

status, body = call("POST", "/api/math/calculus", {"expression": "x^3 - 3x", "x0": 2, "a": -2, "b": 2})
check("calculus: d/dx (x^3 - 3x) = 3x^2 - 3, tangent y = 9x - 16",
      status == 200 and body["derivative"]["text"] == "3x^2 \u2212 3" and body["tangent"]["text"] == "y = 9x \u2212 16",
      body if status != 200 else body["derivative"])

status, body = call("POST", "/api/math/statistics", {"x": "2 4 4 4 5 5 7 9", "mode": "population"})
check("statistics: mean 5, standard deviation 2", status == 200 and body.get("mean") == 5 and body.get("std") == 2, body)

status, body = call("POST", "/api/math/solid", {"shape": "cylinder", "dims": {"r": 3, "h": 10}, "unit": "cm"})
volume = body["results"][0]["value"] if status == 200 else None
check("3D shapes: cylinder r = 3, h = 10 holds 282.74 cm3", close(volume, 282.743, 0.001), body)

print("\nMatrices and vectors (matrix-service)")
status, body = call("POST", "/api/matrix/matrix", {"operation": "inverse",
                                                    "a": [["2", "-1", "0"], ["-1", "2", "-1"], ["0", "-1", "2"]]})
first_row = [c["text"] for c in body["matrix"][0]] if status == 200 else None
check("inverse with exact fractions: first row 3/4, 1/2, 1/4", first_row == ["3/4", "1/2", "1/4"], body)

status, body = call("POST", "/api/matrix/matrix", {"operation": "solve", "a": [["2", "1"], ["1", "3"]], "b": [["3"], ["5"]]})
solution = [row[0]["text"] for row in body["solution"]] if status == 200 and body.get("solution") else None
check("simultaneous equations: x = 4/5, y = 7/5", solution == ["4/5", "7/5"], body)

status, body = call("POST", "/api/matrix/vector3d", {"a": [1, 2, 3], "b": [4, -1, 2]})
check("3D vectors: a . b = 8, a x b = (7, 10, -9)",
      status == 200 and body.get("dot") == 8 and body.get("cross") == [7, 10, -9], body)

print("\nWorked solutions (solver-service)")
status, body = call("POST", "/api/solver/ask", {"text": "EMI for 10 lakh at 8.5% for 20 years"})
check("Ask box: EMI for 10 lakh at 8.5% for 20 years is Rs 8,678.23 a month, with steps",
      status == 200 and "8,678.23" in str(body.get("answer")) and len(body.get("steps", [])) >= 5, body)
check("Ask box says which services helped", status == 200 and {"finance-service"} <= {u["service"] for u in body.get("used", [])}, body)

status, body = call("POST", "/api/solver/ask", {"text": "derivative of x^2 sin(x)"})
check("Ask box: derivative of x^2 sin(x) = 2x sin(x) + x^2 cos(x), with the product rule shown",
      status == 200 and "cos" in str(body.get("answer")) and any("roduct" in st["rule"] for st in body.get("steps", [])), body)

status, body = call("POST", "/api/solver/integral", {"expression": "x*exp(x)", "lower": "0", "upper": "2"})
check("integral of x e^x from 0 to 2 = e^2 + 1 = 8.389", status == 200 and "8.389" in str(body), body)

status, body = call("POST", "/api/solver/matrix-steps", {"operation": "determinant", "matrix": [["2", "1"], ["5", "3"]]})
check("matrix steps: determinant of [[2,1],[5,3]] is 1", status == 200 and str(body.get("answer")).strip().endswith("1"), body)

status, body = call("POST", "/api/solver/ask", {"text": "tell me a joke"})
check("a question it can't read gets a clear 422 with examples", status == 422 and body.get("examples"), f"HTTP {status}: {body}")

print("\nChaos lab")
status, body = call("GET", "/api/calc/chaos")
check("the chaos lab is switched on (CHAOS_ENABLED)", status == 200 and "chaos" in body, f"HTTP {status}: {body}")
status, body = call("POST", "/api/calc/chaos", {"mode": "heal"})
check("heal is accepted and the service keeps answering", status == 200 and call("GET", "/api/calc/health")[0] == 200, body)
status, body = call("POST", "/api/calc/chaos", {"mode": "explode"})
check("an unknown fault is refused", status == 400, f"HTTP {status}")
status, body = call("GET", "/api/history/chaos")
check("history-service has a chaos route through the gateway", status == 200, f"HTTP {status}")

print("\nHistory (PostgreSQL)")
status, body = call("GET", "/api/history/records?limit=40")
tools = {r["tool"] for r in body.get("records", [])} if status == 200 else set()
expected = {"calculator", "unit-converter", "gst", "emi", "cgpa", "grades", "attendance",
            "scientific", "plot2d", "graph3d", "calculus", "statistics", "solid", "matrix", "vector3d", "solver"}
check("every tool saved its result", expected <= tools, f"missing: {sorted(expected - tools)}")

status, body = call("GET", "/api/history/stats")
check("stats endpoint counts saved results", status == 200 and body.get("total", 0) >= 15, body)

status, body = call("POST", "/api/history/records", {"tool": "calculator", "summary": "fake"})
check("the browser can't write history directly (gateway blocks POST)", status == 403, f"HTTP {status}")

print("\n" + ("All checks passed." if failures == 0 else f"{failures} check(s) failed."))
sys.exit(1 if failures else 0)
