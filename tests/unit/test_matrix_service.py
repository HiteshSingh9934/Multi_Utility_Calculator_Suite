"""Unit tests for matrix-service: exact matrix algebra with fractions, and 3D vectors."""
import math

import pytest

from service_loader import load_service, post

client = load_service("matrix-service").app.test_client()

TRIDIAGONAL = [["2", "-1", "0"], ["-1", "2", "-1"], ["0", "-1", "2"]]


def texts(matrix):
    return [[cell["text"] for cell in row] for row in matrix]


def matrix(operation, a, **extra):
    return post(client, "/matrix", {"operation": operation, "a": a, **extra})


def test_determinant_and_trace():
    assert matrix("determinant", TRIDIAGONAL)["value"]["text"] == "4"
    assert matrix("determinant", [["1/2", "1/3"], ["1/4", "1/5"]])["value"]["text"] == "1/60"   # exact, not 0.01666…
    assert matrix("determinant", [["1", "2"], ["2", "4"]])["value"]["text"] == "0"
    assert matrix("trace", TRIDIAGONAL)["value"]["text"] == "6"


def test_inverse_is_exact():
    body = matrix("inverse", TRIDIAGONAL)
    assert texts(body["matrix"]) == [["3/4", "1/2", "1/4"], ["1/2", "1", "1/2"], ["1/4", "1/2", "3/4"]]
    assert body["determinant"]["text"] == "4"


def test_inverse_of_singular_matrix():
    body = post(client, "/matrix", {"operation": "inverse", "a": [["1", "2"], ["2", "4"]]}, 400)
    assert body["error"].startswith("A has no inverse because its determinant is 0")


def test_multiply_add_transpose_scalar():
    product = matrix("multiply", TRIDIAGONAL, b=[["1"], ["0"], ["1"]])["matrix"]
    assert texts(product) == [["2"], ["−2"], ["2"]]           # answers use a real minus sign, −
    assert [row[0]["value"] for row in product] == [2, -2, 2]  # and a plain number alongside
    assert texts(matrix("add", [["1", "2"]], b=[["3", "4"]])["matrix"]) == [["4", "6"]]
    assert texts(matrix("subtract", [["1", "2"]], b=[["3", "4"]])["matrix"]) == [["−2", "−2"]]
    assert texts(matrix("transpose", [["1", "2", "3"]])["matrix"]) == [["1"], ["2"], ["3"]]
    assert texts(matrix("scalar", [["1", "2"]], scalar="1/2")["matrix"]) == [["1/2", "1"]]


def test_power():
    assert texts(matrix("power", [["1", "1"], ["1", "0"]], power=10)["matrix"]) == [["89", "55"], ["55", "34"]]
    assert texts(matrix("power", [["2", "0"], ["0", "4"]], power=-1)["matrix"]) == [["1/2", "0"], ["0", "1/4"]]
    assert texts(matrix("power", [["5", "7"], ["1", "3"]], power=0)["matrix"]) == [["1", "0"], ["0", "1"]]


def test_rref_and_rank():
    body = matrix("rref", [["1", "2", "3"], ["2", "4", "6"], ["1", "0", "1"]])
    assert body["rank"] == 2 and body["pivots"] == [1, 2]
    assert texts(body["matrix"])[2] == ["0", "0", "0"]
    assert matrix("rank", TRIDIAGONAL)["value"]["text"] == "3"


@pytest.mark.parametrize("a,b,status,solution", [
    (TRIDIAGONAL, [["1"], ["0"], ["1"]], "unique", [["1"], ["1"], ["1"]]),
    ([["2", "1"], ["1", "3"]], [["3"], ["5"]], "unique", [["4/5"], ["7/5"]]),
    ([["1", "1"], ["2", "2"]], [["2"], ["4"]], "infinite", None),
    ([["1", "1"], ["1", "1"]], [["1"], ["2"]], "none", None),
])
def test_solve(a, b, status, solution):
    body = matrix("solve", a, b=b)
    assert body["status"] == status
    if solution:
        assert texts(body["solution"]) == solution


def test_eigen():
    body = matrix("eigen", [["2", "1"], ["1", "2"]])
    assert [p["value"]["text"] for p in body["pairs"]] == ["3", "1"]
    assert body["polynomial"] == "λ^2 − 4λ + 3" and body["symmetric"] is True
    rotation = matrix("eigen", [["0", "-1"], ["1", "0"]])      # a 90° rotation: no real eigenvalues
    assert sorted(p["value"]["imag"] for p in rotation["pairs"]) == [-1, 1]


@pytest.mark.parametrize("body,message", [
    ({"operation": "determinant", "a": [["1", "x"], ["3", "4"]]}, "A row 1, column 2: 'x' isn't a number or a fraction like 3/4"),
    ({"operation": "determinant", "a": [["1", "2"], ["3"]]}, "Every row of matrix A needs the same number of columns"),
    ({"operation": "determinant", "a": [["1", "2", "3"]]}, "det(A) needs a square matrix, but A is 1×3"),
    ({"operation": "determinant", "a": [["1"]] * 9}, "Matrix A can have at most 8 rows"),
    ({"operation": "determinant", "a": [["1/0"]]}, "A row 1, column 1: a fraction can't have 0 at the bottom"),
    ({"operation": "multiply", "a": [["1", "2"]], "b": [["1", "2"]]}, "A has 2 columns but B has 1 row"),
    ({"operation": "add", "a": [["1"]], "b": [["1", "2"]]}, "To add matrices they must be the same size"),
    ({"operation": "power", "a": [["1"]], "power": "1.5"}, "The power n must be a whole number"),
    ({"operation": "power", "a": [["1", "2"], ["2", "4"]], "power": -1}, "A negative power needs an inverse"),
    ({"operation": "cube", "a": [["1"]]}, "Operation must be one of"),
])
def test_matrix_errors(body, message):
    assert post(client, "/matrix", body, 400)["error"].startswith(message)


def test_vectors():
    body = post(client, "/vector3d", {"a": [1, 2, 3], "b": [4, -1, 2], "c": [0, 1, 3]})
    assert body["dot"] == 8 and body["cross"] == [7, 10, -9]
    assert math.isclose(body["magnitude_a"], math.sqrt(14), rel_tol=1e-9)
    assert math.isclose(body["angle_degrees"], 62.188157, rel_tol=1e-7)
    assert body["triple_product"] == -17 and body["coplanar"] is False
    assert body["perpendicular"] is False and body["parallel"] is False


def test_vector_special_cases():
    assert post(client, "/vector3d", {"a": [1, 0, 0], "b": [0, 1, 0]})["perpendicular"] is True
    assert post(client, "/vector3d", {"a": [1, 2, 3], "b": [2, 4, 6]})["parallel"] is True
    zero = post(client, "/vector3d", {"a": [0, 0, 0], "b": [1, 2, 3]})
    assert zero["angle_degrees"] is None and zero["unit_a"] is None
    assert post(client, "/vector3d", {"a": ["1/2", 0, 0], "b": [0, 0, 2]})["cross"] == [0, -1, 0]
    assert post(client, "/vector3d", {"a": [1, 2], "b": [1, 2, 3]}, 400)["field"] == "a"


def test_health_and_metrics():
    assert client.get("/health").get_json()["service"] == "matrix-service"
    matrix("determinant", [["1"]])
    text = client.get("/metrics").get_data(as_text=True)
    assert 'http_requests_total{endpoint="/matrix",method="POST",service="matrix-service",status="200"}' in text
