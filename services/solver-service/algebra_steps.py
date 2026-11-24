"""Worked solutions for equations and matrices.

Steps are {"rule", "text", "math"} like calculus_steps.py; a matrix step also has "matrix":
{"rows": [["1", "2"], ["3", "4"]], "split": None or the number of columns before the divider line}.
Matrix arithmetic uses exact fractions, so 1/3 stays 1/3.
"""
import re
from fractions import Fraction

import sympy as sp

from calculus_steps import Steps, Unsupported, text

MAX_SIZE = 6


# ---------------------------------------------------------------------------
# Equations
# ---------------------------------------------------------------------------

def _roots_text(values):
    shown = [text(v) for v in values]
    return " and ".join(shown) if len(shown) <= 2 else ", ".join(shown[:-1]) + " and " + shown[-1]


def _decimal(value):
    number = complex(sp.N(value, 12))
    if abs(number.imag) < 1e-12:
        return float(f"{number.real:.10g}")
    return {"re": float(f"{number.real:.10g}"), "im": float(f"{number.imag:.10g}")}


def solve_equation(left, right, x):
    """-> (solutions as a list of expressions, steps). `left` and `right` are SymPy expressions."""
    s = Steps()
    name = str(x)
    difference = sp.expand(left - right)
    if right != 0:
        s.add("Move everything to one side", "Subtract the right-hand side from both sides so the equation equals 0.",
              f"{text(difference)} = 0")
    else:
        s.add("Start", "The equation already equals 0.", f"{text(left)} = 0")

    if not difference.has(x):
        if difference == 0:
            raise Unsupported(f"Every value of {name} is a solution: the two sides are always equal.")
        raise Unsupported(f"There is no solution: the equation reduces to {text(difference)} = 0, which is never true.")

    if difference.is_polynomial(x):
        poly = sp.Poly(difference, x)
        degree = poly.degree()
        coefficients = poly.all_coeffs()
        if degree == 1:
            a, b = coefficients
            s.add("Linear equation", f"The equation has the form a{name} + b = 0 with a = {text(a)} and b = {text(b)}.",
                  f"{text(a)}{name} + {text(b)} = 0" if b >= 0 else f"{text(a)}{name} − {text(-b)} = 0")
            s.add("Subtract b from both sides", f"{text(a)}{name} = {text(-b)}")
            solution = -b / a
            s.add("Divide by a", f"Divide both sides by {text(a)}.", f"{name} = {text(solution)}")
            solutions = [solution]
        elif degree == 2:
            a, b, c = coefficients
            s.add("Quadratic equation", f"It has the form a{name}² + b{name} + c = 0 with a = {text(a)}, b = {text(b)}, c = {text(c)}.")
            disc = b ** 2 - 4 * a * c
            s.add("Discriminant", "D = b² − 4ac tells how many real solutions there are: two if D > 0, one if D = 0, none if D < 0.",
                  f"D = ({text(b)})² − 4·({text(a)})·({text(c)}) = {text(disc)}")
            factored = sp.factor(difference)
            if factored.is_Mul or factored.is_Pow:
                s.add("Factorise", "Write the quadratic as a product; the product is 0 when one of the factors is 0.",
                      f"{text(factored)} = 0")
            root = sp.sqrt(disc)
            if disc > 0:
                s.add("Quadratic formula", f"{name} = (−b ± √D) / 2a. D is positive, so there are two real solutions.",
                      f"{name} = (−({text(b)}) ± {text(root)}) / (2·{text(a)})")
            elif disc == 0:
                s.add("Quadratic formula", f"{name} = −b / 2a. D is 0, so there is one repeated solution.",
                      f"{name} = −({text(b)}) / (2·{text(a)})")
            else:
                s.add("Quadratic formula", f"{name} = (−b ± √D) / 2a. D is negative, so the solutions are complex numbers.",
                      f"{name} = (−({text(b)}) ± {text(root)}) / (2·{text(a)})")
            solutions = sorted(sp.solve(difference, x), key=lambda v: (sp.re(v), sp.im(v)))
            s.add("Solutions", "Work out both values." if len(solutions) > 1 else "The solution.",
                  f"{name} = {_roots_text(solutions)}")
        else:
            factored = sp.factor(difference)
            if factored.is_Mul or factored.is_Pow:
                s.add("Factorise", "Write the polynomial as a product of simpler factors. The product is 0 when a factor is 0.",
                      f"{text(factored)} = 0")
            else:
                s.add("No simple factors", f"This degree-{degree} polynomial does not factor over the rationals, "
                      "so the roots are found numerically.")
            solutions = list(sp.Poly(difference, x).nroots(n=12)) if not factored.is_Mul else sorted(
                sp.solve(difference, x), key=lambda v: (sp.re(sp.N(v)), sp.im(sp.N(v))))
            if any(sp.count_ops(v) > 25 for v in solutions):
                solutions = list(sp.Poly(difference, x).nroots(n=12))
            s.add("Solutions", f"A polynomial of degree {degree} has {degree} roots, counting repeats and complex ones.",
                  f"{name} = {_roots_text(sorted(set(solutions), key=lambda v: (sp.re(sp.N(v)), sp.im(sp.N(v)))))}")
            solutions = sorted(set(solutions), key=lambda v: (sp.re(sp.N(v)), sp.im(sp.N(v))))
    else:
        found = sp.solveset(difference, x, domain=sp.S.Reals)
        if not isinstance(found, sp.FiniteSet) or not len(found):
            raise Unsupported("This equation has no solution that can be written down exactly. "
                              "Plot both sides in the Function plotter to find where they meet.")
        solutions = sorted(found, key=lambda v: float(sp.N(v)))
        s.add("Solve", "SymPy solves this equation over the real numbers.", f"{name} = {_roots_text(solutions)}")

    # Check by substituting back
    shown = solutions[0]
    residual = sp.simplify(difference.subs(x, shown))
    if residual != 0 and abs(complex(sp.N(residual))) > 1e-8:
        raise Unsupported("The solution could not be verified.")
    s.add("Check", f"Substitute {name} = {text(shown)} back into the equation.",
          f"{text(left.subs(x, shown))} = {text(right.subs(x, shown))}" if len(text(left.subs(x, shown))) < 60 else "both sides are equal")
    return solutions, s


def decimal_of(value):
    return _decimal(value)


# ---------------------------------------------------------------------------
# Matrices
# ---------------------------------------------------------------------------

def fraction_text(f):
    f = Fraction(f)
    return str(f.numerator).replace("-", "−") if f.denominator == 1 else f"{f.numerator}/{f.denominator}".replace("-", "−")


def parse_cell(value):
    if isinstance(value, bool):
        raise Unsupported("Matrix entries must be numbers")
    if isinstance(value, (int, float)):
        return Fraction(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace("−", "-")
        try:
            return Fraction(cleaned)
        except (ValueError, ZeroDivisionError):
            pass
    raise Unsupported(f"'{value}' is not a number or a fraction such as 1/2")


def parse_matrix(rows, square=False):
    if not isinstance(rows, list) or not rows or not all(isinstance(r, list) and r for r in rows):
        raise Unsupported("Send the matrix as a list of rows, for example [[1, 2], [3, 4]]")
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        raise Unsupported("Every row of the matrix needs the same number of entries")
    if len(rows) > MAX_SIZE or width > MAX_SIZE:
        raise Unsupported(f"The step-by-step solver handles matrices up to {MAX_SIZE}×{MAX_SIZE}")
    matrix = [[parse_cell(v) for v in r] for r in rows]
    if square and len(matrix) != width:
        raise Unsupported(f"The matrix is {len(matrix)}×{width}; this needs a square matrix")
    return matrix


def snapshot(matrix, split=None):
    return {"rows": [[fraction_text(v) for v in row] for row in matrix], "split": split}


def _row_label(i):
    return f"R{i + 1}"


def _scaled(factor, i):
    return f"{fraction_text(factor)}·{_row_label(i)}"


def gauss_jordan(m, columns, s, split=None):
    """Reduce m (in place) to reduced row echelon form, working on the first `columns` columns for pivots.
    Returns the pivot columns."""
    rows = len(m)
    s.add("Start", "The matrix we are reducing." if split is None else "The augmented matrix [A | right-hand side].",
          matrix=snapshot(m, split))
    pivots = []
    r = 0
    for c in range(columns):
        pivot_row = next((i for i in range(r, rows) if m[i][c] != 0), None)
        if pivot_row is None:
            continue
        if pivot_row != r:
            m[r], m[pivot_row] = m[pivot_row], m[r]
            s.add("Swap rows", f"Column {c + 1} needs a non-zero entry in row {r + 1}.", f"{_row_label(r)} ↔ {_row_label(pivot_row)}",
                  matrix=snapshot(m, split))
        pivot = m[r][c]
        if pivot != 1:
            m[r] = [v / pivot for v in m[r]]
            s.add("Make the pivot 1", f"Divide row {r + 1} by {fraction_text(pivot)}.",
                  f"{_row_label(r)} → {_row_label(r)} ÷ {fraction_text(pivot)}", matrix=snapshot(m, split))
        for i in range(rows):
            if i != r and m[i][c] != 0:
                factor = m[i][c]
                m[i] = [a - factor * b for a, b in zip(m[i], m[r])]
                s.add("Clear the column", f"Make the other entries in column {c + 1} zero.",
                      f"{_row_label(i)} → {_row_label(i)} − {_scaled(factor, r)}", matrix=snapshot(m, split))
        pivots.append(c)
        r += 1
        if r == rows:
            break
    return pivots


def rref_steps(rows):
    m = parse_matrix(rows)
    s = Steps()
    pivots = gauss_jordan(m, len(m[0]), s)
    s.add("Done", f"The matrix is in reduced row echelon form. It has {len(pivots)} pivot{'s' if len(pivots) != 1 else ''}, "
          f"so its rank is {len(pivots)}.", matrix=snapshot(m))
    return snapshot(m), s, {"rank": len(pivots)}


def determinant(m):
    n = len(m)
    if n == 1:
        return m[0][0]
    a = [row[:] for row in m]
    sign = 1
    det = Fraction(1)
    for c in range(n):
        pivot = next((i for i in range(c, n) if a[i][c] != 0), None)
        if pivot is None:
            return Fraction(0)
        if pivot != c:
            a[c], a[pivot] = a[pivot], a[c]
            sign = -sign
        det *= a[c][c]
        for i in range(c + 1, n):
            factor = a[i][c] / a[c][c]
            a[i] = [x - factor * y for x, y in zip(a[i], a[c])]
    return sign * det


def _minor(m, i, j):
    return [row[:j] + row[j + 1:] for k, row in enumerate(m) if k != i]


def determinant_steps(rows):
    m = parse_matrix(rows, square=True)
    n = len(m)
    s = Steps()
    f = fraction_text
    s.add("The matrix", f"Find the determinant of this {n}×{n} matrix.", matrix=snapshot(m))
    if n == 1:
        s.add("1×1", "The determinant of a 1×1 matrix is its only entry.", f"det = {f(m[0][0])}")
    elif n == 2:
        (a, b), (c, d) = m
        s.add("2×2 formula", "For [[a, b], [c, d]] the determinant is a·d − b·c.",
              f"det = ({f(a)})·({f(d)}) − ({f(b)})·({f(c)}) = {f(a * d)} − ({f(b * c)}) = {f(a * d - b * c)}")
    elif n == 3:
        s.add("Cofactor expansion along row 1", "Multiply each entry of the first row by the determinant of the 2×2 matrix "
              "left when its row and column are removed, alternating the signs + − +.")
        total = Fraction(0)
        for j in range(3):
            minor = _minor(m, 0, j)
            md = minor[0][0] * minor[1][1] - minor[0][1] * minor[1][0]
            term = (-1) ** j * m[0][j] * md
            total += term
            s.add(f"Entry {f(m[0][j])} (column {j + 1})",
                  f"Remove row 1 and column {j + 1}. The 2×2 determinant is ({f(minor[0][0])})·({f(minor[1][1])}) − "
                  f"({f(minor[0][1])})·({f(minor[1][0])}) = {f(md)}.",
                  f"{'+' if j % 2 == 0 else '−'} {f(m[0][j])} · {f(md)} = {f(term)}", matrix=snapshot(minor))
        s.add("Add the terms", "Add the three results.", f"det = {f(total)}")
    else:
        s.add("Row reduction", "For larger matrices, reduce to upper-triangular form. Adding a multiple of one row to another "
              "does not change the determinant, a row swap flips its sign, and for a triangular matrix the determinant is "
              "the product of the diagonal.")
        a = [row[:] for row in m]
        sign = 1
        for c in range(n):
            pivot = next((i for i in range(c, n) if a[i][c] != 0), None)
            if pivot is None:
                s.add("Zero column", f"Column {c + 1} has no non-zero entry at or below the diagonal, so the determinant is 0.",
                      matrix=snapshot(a))
                break
            if pivot != c:
                a[c], a[pivot] = a[pivot], a[c]
                sign = -sign
                s.add("Swap rows", f"{_row_label(c)} ↔ {_row_label(pivot)}. The sign of the determinant flips.",
                      matrix=snapshot(a))
            for i in range(c + 1, n):
                if a[i][c] != 0:
                    factor = a[i][c] / a[c][c]
                    a[i] = [x - factor * y for x, y in zip(a[i], a[c])]
                    s.add("Clear below the pivot", f"{_row_label(i)} → {_row_label(i)} − {_scaled(factor, c)}", matrix=snapshot(a))
        diagonal = [a[i][i] for i in range(n)]
        product = Fraction(1)
        for v in diagonal:
            product *= v
        s.add("Multiply the diagonal", ("Remember the sign from the row swaps. " if sign < 0 else "") + "The determinant is the product of the diagonal entries.",
              "det = " + ("−" if sign < 0 else "") + "(" + " · ".join(f(v) for v in diagonal) + f") = {f(sign * product)}")
    value = determinant(m)
    return value, s


def inverse_steps(rows):
    m = parse_matrix(rows, square=True)
    n = len(m)
    s = Steps()
    augmented = [row + [Fraction(int(i == j)) for j in range(n)] for i, row in enumerate(m)]
    s.add("Idea", "Write the matrix next to the identity matrix and row-reduce until the left side becomes the identity. "
          "What appears on the right is the inverse.")
    pivots = gauss_jordan(augmented, n, s, split=n)
    if len(pivots) < n:
        s.add("No inverse", "A row of zeros appeared on the left side, so the matrix is singular: its determinant is 0 "
              "and it has no inverse.")
        return None, s
    inverse = [row[n:] for row in augmented]
    s.add("Read off the inverse", "The left side is now the identity, so the right side is the inverse.", matrix=snapshot(inverse))
    return snapshot(inverse), s


def solve_steps(rows, constants):
    m = parse_matrix(rows, square=True)
    n = len(m)
    if not isinstance(constants, list) or len(constants) != n:
        raise Unsupported(f"Give {n} constants, one for each equation")
    b = [parse_cell(v) for v in constants]
    s = Steps()
    augmented = [row + [b[i]] for i, row in enumerate(m)]
    s.add("Set up", "Write the equations as an augmented matrix [coefficients | constants].")
    pivots = gauss_jordan(augmented, n, s, split=n)
    names = ["x", "y", "z", "w", "v", "u"][:n]
    inconsistent = any(all(v == 0 for v in row[:n]) and row[n] != 0 for row in augmented)
    if inconsistent:
        s.add("No solution", "A row reads 0 = non-zero, which is impossible, so the equations contradict each other.")
        return None, s
    if len(pivots) < n:
        s.add("Infinitely many solutions", f"Only {len(pivots)} of the {n} unknowns are fixed by the equations; "
              "the others can take any value.")
        return None, s
    solution = [augmented[i][n] for i in range(n)]
    s.add("Read off the solution", "Each row now says one unknown equals a number.",
          ",   ".join(f"{names[i]} = {fraction_text(v)}" for i, v in enumerate(solution)), matrix=None)
    return solution, s


# ---------------------------------------------------------------------------
# Reading a matrix out of text such as "[[1,2],[3,4]]" or "1 2; 3 4"
# ---------------------------------------------------------------------------

def matrix_from_text(source):
    cleaned = source.strip().replace("−", "-")
    if cleaned.startswith("[["):
        try:
            import json
            rows = json.loads(cleaned)
        except ValueError:
            rows = None
        if isinstance(rows, list):
            return rows
    cleaned = re.sub(r"[\[\]\(\)]", " ", cleaned)
    rows = [r for r in re.split(r"[;\n|]", cleaned) if r.strip()]
    if not rows:
        return None
    result = [[cell for cell in re.split(r"[\s,]+", row.strip()) if cell] for row in rows]
    return result if all(result) else None
