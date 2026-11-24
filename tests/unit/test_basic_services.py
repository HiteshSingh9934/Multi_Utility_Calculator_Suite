"""Unit tests for calc-service, converter-service, finance-service and student-service."""
import math

import pytest

from service_loader import load_service, post

calc = load_service("calc-service").app.test_client()
conv = load_service("converter-service").app.test_client()
fin = load_service("finance-service").app.test_client()
stu = load_service("student-service").app.test_client()


# ---------------- shared behaviour ----------------
@pytest.mark.parametrize("client,name", [(calc, "calc-service"), (conv, "converter-service"),
                                         (fin, "finance-service"), (stu, "student-service")])
def test_health_and_header(client, name):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json()["service"] == name
    assert r.headers["X-Served-By"]


def test_unknown_route_is_json_404():
    r = calc.get("/nope")
    assert r.status_code == 404 and "error" in r.get_json()


def test_wrong_method_is_json_405():
    r = calc.get("/calculate")
    assert r.status_code == 405 and "error" in r.get_json()


def test_non_json_body():
    r = calc.post("/calculate", data="hello", content_type="text/plain")
    assert r.status_code == 400 and r.get_json()["error"] == "Send the inputs as a JSON object"


# ---------------- calc-service ----------------
@pytest.mark.parametrize("op,a,b,expected", [
    ("add", 10, 5, 15), ("subtract", 10, 5, 5), ("multiply", 6, 7, 42), ("divide", 22, 7, 3.14285714286),
    ("power", 2, 10, 1024), ("modulus", 17, 5, 2), ("modulus", -7, 3, -1), ("percent_of", 15, 200, 30),
    ("add", 0.1, 0.2, 0.3), ("add", "4", "5", 9),
])
def test_calculate(op, a, b, expected):
    body = post(calc, "/calculate", {"num1": a, "num2": b, "operation": op})
    assert math.isclose(body["result"], expected, rel_tol=1e-11)
    assert body["saved"] is False  # history-service unreachable, but the result still comes back


def test_calculate_expression_formatting():
    body = post(calc, "/calculate", {"num1": 1234567, "num2": 1, "operation": "add"})
    assert body["expression"] == "12,34,567 + 1 = 12,34,568"
    body = post(calc, "/calculate", {"num1": 15, "num2": 200, "operation": "percent_of"})
    assert body["expression"] == "15% of 200 = 30"


@pytest.mark.parametrize("payload,message", [
    ({"num1": 1, "num2": 0, "operation": "divide"}, "Cannot divide by zero"),
    ({"num1": 1, "num2": 0, "operation": "modulus"}, "Cannot divide by zero"),
    ({"num1": -8, "num2": 0.5, "operation": "power"}, "A negative number can't be raised to a fractional power"),
    ({"num1": 0, "num2": -1, "operation": "power"}, "Zero can't be raised to a negative power"),
    ({"num1": 10, "num2": 400, "operation": "power"}, "The result is too large to calculate"),
    ({"num1": 1e308, "num2": 10, "operation": "multiply"}, "The result is too large to calculate"),
    ({"num1": 1, "num2": 2, "operation": "sqrt"}, "Choose one of"),
    ({"num2": 2, "operation": "add"}, "First number is required"),
    ({"num1": "abc", "num2": 2, "operation": "add"}, "First number must be a number"),
    ({"num1": True, "num2": 2, "operation": "add"}, "First number must be a number"),
])
def test_calculate_errors(payload, message):
    body = post(calc, "/calculate", payload, 400)
    assert body["error"].startswith(message)


# ---------------- converter-service ----------------
def test_units_catalogue():
    cats = conv.get("/units").get_json()["categories"]
    assert [c["id"] for c in cats] == ["length", "weight", "temperature", "area", "volume",
                                        "speed", "time", "data", "energy", "pressure"]
    for c in cats:  # every default unit exists in its category
        ids = {u["id"] for u in c["units"]}
        assert c["default_from"] in ids and c["default_to"] in ids


@pytest.mark.parametrize("cat,value,f,t,expected", [
    ("length", 10, "km", "mi", 6.21371192237), ("length", 1, "mi", "km", 1.609344),
    ("length", 1, "ft", "in", 12), ("weight", 1, "kg", "lb", 2.20462262185), ("weight", 1, "q", "kg", 100),
    ("temperature", 100, "c", "f", 212), ("temperature", 32, "f", "c", 0), ("temperature", 0, "k", "c", -273.15),
    ("temperature", -40, "c", "f", -40), ("temperature", 300, "k", "f", 80.33),
    ("area", 1, "guntha", "ft2", 1089), ("area", 1, "ac", "guntha", 40), ("area", 1, "ha", "ac", 2.47105381467),
    ("volume", 1, "gal", "l", 3.785411784), ("volume", 1, "m3", "l", 1000),
    ("speed", 100, "kmph", "mps", 27.7777777778), ("speed", 60, "mph", "kmph", 96.56064),
    ("time", 2, "h", "min", 120), ("time", 1, "wk", "h", 168),
    ("data", 1, "gib", "mib", 1024), ("data", 1, "gb", "mb", 1000), ("data", 8, "bit", "b", 1),
    ("energy", 1, "kwh", "kj", 3600), ("energy", 1, "kcal", "kj", 4.184),
    ("pressure", 1, "atm", "kpa", 101.325), ("pressure", 2.2, "bar", "psi", 31.9083023006),
])
def test_conversions(cat, value, f, t, expected):
    body = post(conv, "/convert", {"category": cat, "value": value, "from_unit": f, "to_unit": t})
    assert math.isclose(body["result"], expected, rel_tol=1e-9, abs_tol=1e-9), body


def test_convert_include_all_and_summary():
    body = post(conv, "/convert", {"category": "length", "value": 1, "from_unit": "km",
                                   "to_unit": "m", "include_all": True})
    assert body["summary"] == "1 km = 1,000 m"
    assert len(body["all"]) == 11 and any(u["unit"] == "mi" for u in body["all"])


@pytest.mark.parametrize("payload,message", [
    ({"category": "temperature", "value": -5, "from_unit": "k", "to_unit": "c"}, "That is colder than absolute zero"),
    ({"category": "temperature", "value": -500, "from_unit": "f", "to_unit": "c"}, "That is colder than absolute zero"),
    ({"category": "colour", "value": 1, "from_unit": "a", "to_unit": "b"}, "Choose one of"),
    ({"category": "length", "value": 1, "from_unit": "parsec", "to_unit": "m"}, "Unknown unit 'parsec'"),
    ({"category": "length", "from_unit": "m", "to_unit": "km"}, "Value is required"),
])
def test_convert_errors(payload, message):
    assert post(conv, "/convert", payload, 400)["error"].startswith(message)


# ---------------- finance-service: GST ----------------
def test_gst_add_intra():
    b = post(fin, "/gst", {"amount": 1000, "rate": 18, "mode": "exclusive", "supply": "intra"})
    assert (b["net_amount"], b["gst_amount"], b["gross_amount"]) == (1000, 180, 1180)
    assert [(x["label"], x["rate"], x["amount"]) for x in b["breakdown"]] == [("CGST", 9, 90), ("SGST", 9, 90)]
    assert b["summary"] == "18% GST on ₹1,000.00: GST ₹180.00, total ₹1,180.00"


def test_gst_remove_inter():
    b = post(fin, "/gst", {"amount": 1180, "rate": 18, "mode": "inclusive", "supply": "inter"})
    assert (b["net_amount"], b["gst_amount"], b["gross_amount"]) == (1000, 180, 1180)
    assert b["breakdown"] == [{"label": "IGST", "rate": 18, "amount": 180}]


@pytest.mark.parametrize("amount,rate,mode", [(100.05, 5, "exclusive"), (999.99, 18, "inclusive"),
                                              (12345.67, 0.25, "exclusive"), (1, 3, "inclusive"),
                                              (250000, 40, "exclusive"), (7.77, 5, "inclusive")])
def test_gst_paise_always_add_up(amount, rate, mode):
    b = post(fin, "/gst", {"amount": amount, "rate": rate, "mode": mode, "supply": "intra"})
    cgst, sgst = (x["amount"] for x in b["breakdown"])
    assert round(cgst + sgst, 2) == b["gst_amount"]
    assert round(b["net_amount"] + b["gst_amount"], 2) == b["gross_amount"]
    assert abs(cgst - sgst) <= 0.01 + 1e-9


def test_gst_rates_and_errors():
    slabs = fin.get("/gst/rates").get_json()["slabs"]
    assert [s["rate"] for s in slabs][:3] == [5, 18, 40]
    assert post(fin, "/gst", {"amount": 0, "rate": 18}, 400)["error"] == "Amount must be more than 0"
    assert post(fin, "/gst", {"amount": 10, "rate": 140}, 400)["error"] == "GST rate can't be more than 100"
    assert post(fin, "/gst", {"amount": 10, "rate": 18, "mode": "both"}, 400)["field"] == "mode"


# ---------------- finance-service: EMI ----------------
def test_emi_standard_loan():
    b = post(fin, "/emi", {"principal": 500000, "annual_rate": 9, "tenure": 5, "tenure_unit": "years"})
    assert 10379.0 < b["emi"] < 10379.5 and b["months"] == 60
    assert len(b["yearly"]) == 5 and b["yearly"][-1]["balance"] == 0
    assert math.isclose(sum(y["principal"] for y in b["yearly"]), 500000, abs_tol=0.05)
    assert math.isclose(b["total_payment"], 500000 + b["total_interest"], abs_tol=0.01)
    assert b["summary"].startswith("EMI ₹10,379.")


def test_emi_zero_rate_and_months():
    b = post(fin, "/emi", {"principal": 120000, "annual_rate": 0, "tenure": 18, "tenure_unit": "months"})
    assert b["emi"] == 6666.67 and b["total_interest"] == 0 and b["tenure_text"] == "1 year 6 months"
    assert len(b["yearly"]) == 2 and b["yearly"][-1]["balance"] == 0


def test_emi_monthly_schedule_and_errors():
    b = post(fin, "/emi", {"principal": 100000, "annual_rate": 12, "tenure": 1, "include_monthly": True})
    assert len(b["monthly"]) == 12 and b["monthly"][-1]["balance"] == 0
    assert post(fin, "/emi", {"principal": 1000, "annual_rate": 9, "tenure": 1.03}, 400)["field"] == "tenure"
    assert post(fin, "/emi", {"principal": 1000, "annual_rate": 9, "tenure": 41}, 400)["field"] == "tenure"
    assert post(fin, "/emi", {"principal": -5, "annual_rate": 9, "tenure": 1}, 400)["field"] == "principal"


# ---------------- student-service ----------------
def test_cgpa_presets():
    b = post(stu, "/cgpa", {"direction": "to_percentage", "value": 8.2, "formula": "mitadt"})
    assert b["result"] == 78.39 and b["formula_text"] == "CGPA × 9.56"
    b = post(stu, "/cgpa", {"direction": "to_cgpa", "value": 78.39, "formula": "mitadt"})
    assert b["result"] == 8.2
    assert post(stu, "/cgpa", {"value": 8, "formula": "cbse"})["result"] == 76
    assert post(stu, "/cgpa", {"value": 8, "formula": "minus075"})["result"] == 72.5


def test_cgpa_custom_and_clamp():
    b = post(stu, "/cgpa", {"value": 9, "formula": "custom", "multiplier": 7.1, "offset": 11})
    assert b["result"] == 74.9 and b["formula_text"] == "CGPA × 7.1 + 11"
    b = post(stu, "/cgpa", {"value": 0.5, "formula": "minus075"})
    assert b["result"] == 0 and b["clamped"] is True
    assert post(stu, "/cgpa", {"value": 11, "formula": "cbse"}, 400)["error"] == "CGPA can't be more than 10"
    assert post(stu, "/cgpa", {"value": 8, "formula": "custom", "offset": 1}, 400)["field"] == "multiplier"


def test_grades_with_sgpa():
    subjects = [
        {"name": "Maths", "marks": 92, "credits": 4},
        {"name": "Physics", "marks": 78, "credits": 3},
        {"name": "Chemistry", "marks": 64, "credits": 3},
        {"name": "Lab", "marks": 45, "max_marks": 50, "credits": 2},
        {"name": "English", "marks": 38, "credits": 2},
    ]
    b = post(stu, "/grades", {"subjects": subjects})
    grades = [s["grade"] for s in b["subjects"]]
    assert grades == ["O", "A", "B+", "O", "F"]
    assert b["total_marks"] == 317 and b["total_max"] == 450 and b["percentage"] == 70.44
    assert b["overall_grade"] == "A" and b["failed_subjects"] == ["English"]
    # SGPA = (4*10 + 3*8 + 3*7 + 2*10 + 2*0) / 14 = 105/14 = 7.5
    assert b["sgpa"] == 7.5 and b["same_max_marks"] is False


@pytest.mark.parametrize("pct,grade", [(90, "O"), (89.99, "A+"), (80, "A+"), (70, "A"), (60, "B+"),
                                       (50, "B"), (45, "C"), (40, "P"), (39.99, "F"), (0, "F")])
def test_grade_boundaries(pct, grade):
    b = post(stu, "/grades", {"subjects": [{"marks": pct, "max_marks": 100}]})
    assert b["subjects"][0]["grade"] == grade and b["sgpa"] is None


def test_grades_errors():
    assert post(stu, "/grades", {"subjects": []}, 400)["field"] == "subjects"
    err = post(stu, "/grades", {"subjects": [{"name": "Maths", "marks": 120}]}, 400)
    assert err["error"] == "Maths: marks can't be more than 100"


@pytest.mark.parametrize("attended,total,required,field,value", [
    (42, 60, 75, "must_attend", 12),   # 54/72 = 75%
    (50, 60, 75, "can_miss", 6),       # 50/66 = 75.8%, 50/67 = 74.6%
    (45, 60, 75, "can_miss", 0),       # exactly at the limit
    (59, 60, 66.67, "can_miss", 28),
    (10, 30, 50, "must_attend", 10),   # 20/40 = 50%
])
def test_attendance(attended, total, required, field, value):
    b = post(stu, "/attendance", {"attended": attended, "total": total, "required": required})
    assert b[field] == value, b
    if field == "must_attend":
        x = value
        assert (attended + x) * 100 / (total + x) >= required and (attended + x - 1) * 100 / (total + x - 1) < required
    elif value:
        assert attended * 100 / (total + value) >= required and attended * 100 / (total + value + 1) < required


def test_attendance_edge_cases():
    b = post(stu, "/attendance", {"attended": 59, "total": 60, "required": 100})
    assert b["must_attend"] is None and "can't reach 100%" in b["message"]
    b = post(stu, "/attendance", {"attended": 60, "total": 60, "required": 100})
    assert b["can_miss"] == 0 and b["meets_requirement"] is True
    b = post(stu, "/attendance", {"attended": 30, "total": 40})
    assert b["required"] == 75 and b["percentage"] == 75 and b["can_miss"] == 0
    assert post(stu, "/attendance", {"attended": 61, "total": 60}, 400)["field"] == "attended"
    assert post(stu, "/attendance", {"attended": 4.5, "total": 60}, 400)["error"] == "Classes attended must be a whole number"


# ---------------- Prometheus metrics (every service) ----------------
@pytest.mark.parametrize("client,name", [(calc, "calc-service"), (conv, "converter-service"),
                                         (fin, "finance-service"), (stu, "student-service")])
def test_metrics_count_requests(client, name):
    client.get("/health")          # health checks are not counted: they would drown out real traffic
    client.get("/no-such-page")
    response = client.get("/metrics")
    assert response.status_code == 200 and response.mimetype == "text/plain"
    text = response.get_data(as_text=True)
    assert f'http_requests_total{{endpoint="unmatched",method="GET",service="{name}",status="404"}}' in text
    assert "http_request_duration_seconds_bucket" in text
    assert 'endpoint="/health"' not in text
