"""Worked solutions for the EMI and GST calculators (the same formulas finance-service uses)."""
from calculus_steps import Steps, Unsupported

MAX_MONTHS = 480


def group_indian(digits):
    """'1234567' -> '12,34,567'"""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join(pairs) + "," + tail


def inr(value, decimals=2):
    sign = "−" if value < 0 else ""
    whole, _, fraction = f"{abs(value):.{decimals}f}".partition(".")
    return f"{sign}₹{group_indian(whole)}" + (f".{fraction}" if fraction else "")


def num(value, digits=6):
    """A plain number: 0.0075 stays 0.0075, 1.5 stays 1.5, 3.0 becomes 3."""
    text = f"{value:.{digits}g}"
    if "e" in text:
        return f"{value:.10f}".rstrip("0").rstrip(".")
    return text


def tenure_text(months):
    years, rest = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} year" + ("s" if years != 1 else ""))
    if rest:
        parts.append(f"{rest} month" + ("s" if rest != 1 else ""))
    return " ".join(parts)


def emi_steps(principal, annual_rate, months):
    """-> (numbers, steps). months must be a whole number."""
    if principal <= 0:
        raise Unsupported("The loan amount must be more than 0")
    if not 0 <= annual_rate <= 50:
        raise Unsupported("The interest rate must be between 0% and 50%")
    if not 1 <= months <= MAX_MONTHS:
        raise Unsupported("The tenure must be between 1 month and 40 years")

    s = Steps()
    s.add("What we know", "The loan amount, the yearly interest rate and the number of monthly payments.",
          f"P = {inr(principal, 0 if principal == int(principal) else 2)},   yearly rate = {num(annual_rate)}%,   n = {months} months ({tenure_text(months)})")
    r = annual_rate / 12 / 100
    s.add("Monthly interest rate", "Interest is charged every month, so divide the yearly rate by 12 and by 100.",
          f"r = {num(annual_rate)} ÷ 12 ÷ 100 = {num(r, 8)}")
    if r == 0:
        emi = principal / months
        s.add("No interest", "With 0% interest the loan is just split into equal parts.",
              f"EMI = P ÷ n = {inr(principal, 2)} ÷ {months} = {inr(emi)}")
    else:
        s.add("The EMI formula", "Each month you pay the same amount, chosen so that the balance reaches exactly 0 after n payments.",
              "EMI = P × r × (1 + r)ⁿ ÷ ((1 + r)ⁿ − 1)")
        growth = (1 + r) ** months
        s.add("Growth factor", f"Work out (1 + r)ⁿ: one month's growth repeated {months} times.",
              f"(1 + {num(r, 8)})^{months} = {num(growth, 8)}")
        emi = principal * r * growth / (growth - 1)
        s.add("Substitute", "Put the numbers into the formula.",
              f"EMI = {num(principal)} × {num(r, 8)} × {num(growth, 8)} ÷ ({num(growth, 8)} − 1) = {inr(emi)}")
    total_payment = emi * months
    total_interest = total_payment - principal
    s.add("Total paid", f"{months} payments of {inr(emi)}.", f"{inr(emi)} × {months} = {inr(total_payment)}")
    s.add("Total interest", "What you pay beyond the amount you borrowed.",
          f"{inr(total_payment)} − {inr(principal, 0 if principal == int(principal) else 2)} = {inr(total_interest)}")
    first_interest = principal * r
    s.add("Where the first payment goes", "Interest is charged on the full balance, so the first payment is mostly interest. "
          "Later payments carry less interest and repay more of the loan.",
          f"interest {inr(first_interest)} + loan repaid {inr(emi - first_interest)} = {inr(emi)}")
    return {"emi": round(emi, 2), "total_interest": round(total_interest, 2),
            "total_payment": round(principal + total_interest, 2), "months": months}, s


def gst_steps(amount, rate, mode="exclusive"):
    """-> (numbers, steps). mode 'exclusive': the amount is before GST; 'inclusive': GST is already in it."""
    if amount <= 0:
        raise Unsupported("The amount must be more than 0")
    if not 0 <= rate <= 100:
        raise Unsupported("The GST rate must be between 0% and 100%")
    s = Steps()
    if mode == "exclusive":
        s.add("What we know", "The price before GST and the GST rate.", f"price = {inr(amount)},   rate = {num(rate)}%")
        tax = round(amount * rate / 100, 2)
        s.add("GST amount", "GST is the rate as a fraction of the price.",
              f"{inr(amount)} × {num(rate)} ÷ 100 = {inr(tax)}")
        total = amount + tax
        s.add("Total to pay", "Add the GST to the price.", f"{inr(amount)} + {inr(tax)} = {inr(total)}")
        return {"net": round(amount, 2), "gst": tax, "gross": round(total, 2)}, s
    s.add("What we know", "The price already includes GST, so the real price is smaller.", f"price with GST = {inr(amount)},   rate = {num(rate)}%")
    net = round(amount * 100 / (100 + rate), 2)
    s.add("Price before GST", f"The price with GST is (100 + {num(rate)})% of the price before GST, so multiply by 100 and divide by {num(100 + rate)}.",
          f"{inr(amount)} × 100 ÷ {num(100 + rate)} = {inr(net)}")
    tax = round(amount - net, 2)
    s.add("GST amount", "What is left is the GST.", f"{inr(amount)} − {inr(net)} = {inr(tax)}")
    return {"net": net, "gst": tax, "gross": round(amount, 2)}, s
