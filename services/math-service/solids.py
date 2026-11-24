"""3D shapes: volume, surface area and other measurements."""
import math

PI = math.pi

# id: (name, [(dimension key, label)], extra rule)
SHAPES = {
    "cube": ("Cube", [("a", "Side")]),
    "cuboid": ("Cuboid", [("l", "Length"), ("w", "Width"), ("h", "Height")]),
    "cylinder": ("Cylinder", [("r", "Radius"), ("h", "Height")]),
    "cone": ("Cone", [("r", "Radius"), ("h", "Height")]),
    "sphere": ("Sphere", [("r", "Radius")]),
    "hemisphere": ("Hemisphere", [("r", "Radius")]),
    "frustum": ("Frustum", [("R", "Bottom radius"), ("r", "Top radius"), ("h", "Height")]),
    "pyramid": ("Square pyramid", [("a", "Base side"), ("h", "Height")]),
    "torus": ("Torus", [("R", "Ring radius"), ("r", "Tube radius")]),
}

# How many litres one cubic unit holds
LITRES_PER_CUBIC_UNIT = {"mm": 1e-6, "cm": 1e-3, "m": 1000.0, "in": 0.016387064, "ft": 28.316846592}


def catalogue():
    return [
        {"id": shape_id, "name": name, "dims": [{"key": key, "label": label} for key, label in dims]}
        for shape_id, (name, dims) in SHAPES.items()
    ]


def measure(shape, d):
    """Returns a list of (label, value, kind, formula). kind is volume, area or length.

    Raises ValueError with a readable message for impossible shapes.
    """
    if shape == "cube":
        a = d["a"]
        return [
            ("Volume", a ** 3, "volume", "V = a³"),
            ("Total surface area", 6 * a * a, "area", "TSA = 6a²"),
            ("Lateral surface area", 4 * a * a, "area", "LSA = 4a²"),
            ("Space diagonal", a * math.sqrt(3), "length", "d = a√3"),
        ]
    if shape == "cuboid":
        l, w, h = d["l"], d["w"], d["h"]
        return [
            ("Volume", l * w * h, "volume", "V = lwh"),
            ("Total surface area", 2 * (l * w + w * h + h * l), "area", "TSA = 2(lw + wh + hl)"),
            ("Lateral surface area", 2 * h * (l + w), "area", "LSA = 2h(l + w)"),
            ("Space diagonal", math.sqrt(l * l + w * w + h * h), "length", "d = √(l² + w² + h²)"),
        ]
    if shape == "cylinder":
        r, h = d["r"], d["h"]
        return [
            ("Volume", PI * r * r * h, "volume", "V = πr²h"),
            ("Curved surface area", 2 * PI * r * h, "area", "CSA = 2πrh"),
            ("Total surface area", 2 * PI * r * (r + h), "area", "TSA = 2πr(r + h)"),
        ]
    if shape == "cone":
        r, h = d["r"], d["h"]
        slant = math.hypot(r, h)
        return [
            ("Volume", PI * r * r * h / 3, "volume", "V = ⅓πr²h"),
            ("Curved surface area", PI * r * slant, "area", "CSA = πrl"),
            ("Total surface area", PI * r * (slant + r), "area", "TSA = πr(l + r)"),
            ("Slant height", slant, "length", "l = √(r² + h²)"),
        ]
    if shape == "sphere":
        r = d["r"]
        return [
            ("Volume", 4 / 3 * PI * r ** 3, "volume", "V = ⁴⁄₃πr³"),
            ("Surface area", 4 * PI * r * r, "area", "SA = 4πr²"),
        ]
    if shape == "hemisphere":
        r = d["r"]
        return [
            ("Volume", 2 / 3 * PI * r ** 3, "volume", "V = ⅔πr³"),
            ("Curved surface area", 2 * PI * r * r, "area", "CSA = 2πr²"),
            ("Total surface area", 3 * PI * r * r, "area", "TSA = 3πr²"),
        ]
    if shape == "frustum":
        big, small, h = d["R"], d["r"], d["h"]
        if small > big:
            raise ValueError("The top radius can't be larger than the bottom radius")
        slant = math.hypot(h, big - small)
        curved = PI * (big + small) * slant
        return [
            ("Volume", PI * h * (big * big + big * small + small * small) / 3, "volume", "V = ⅓πh(R² + Rr + r²)"),
            ("Curved surface area", curved, "area", "CSA = π(R + r)l"),
            ("Total surface area", curved + PI * (big * big + small * small), "area", "TSA = π(R + r)l + πR² + πr²"),
            ("Slant height", slant, "length", "l = √(h² + (R − r)²)"),
        ]
    if shape == "pyramid":
        a, h = d["a"], d["h"]
        slant = math.hypot(h, a / 2)
        return [
            ("Volume", a * a * h / 3, "volume", "V = ⅓a²h"),
            ("Lateral surface area", 2 * a * slant, "area", "LSA = 2as"),
            ("Total surface area", a * a + 2 * a * slant, "area", "TSA = a² + 2as"),
            ("Slant height", slant, "length", "s = √(h² + (a/2)²)"),
        ]
    if shape == "torus":
        big, small = d["R"], d["r"]
        if small >= big:
            raise ValueError("The tube radius must be smaller than the ring radius")
        return [
            ("Volume", 2 * PI * PI * big * small * small, "volume", "V = 2π²Rr²"),
            ("Surface area", 4 * PI * PI * big * small, "area", "SA = 4π²Rr"),
        ]
    raise ValueError("Unknown shape")
