import re
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value):
    parser = TextParser()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())


def decimal_number(value):
    try:
        result = Decimal(str(value).replace(",", "").strip())
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def price_paisa(value):
    if value is None:
        return None
    cleaned = re.sub(r"^(?:PKR|Rs\.?|₨)\s*", "", str(value).strip(), flags=re.I)
    number = decimal_number(cleaned)
    if number is None or number > 100_000_000 or number.as_tuple().exponent < -2:
        return None
    return int(number * 100)


def package_size(text):
    """Only accept an unambiguous advertised size, never shipping weight."""
    text = unescape(str(text)).lower()
    if re.search(r"\d\s*/\s*\d|\d\s*\+\s*\d", text):
        return None
    units = r"kg|kgs|kilograms?|gm|gms|grams?|g|ml|litres?|liters?|ltr|l|pcs?|pieces?|count"
    pattern = rf"(?:(\d+)\s*[x×]\s*)?(\d+(?:\.\d+)?)\s*({units})\b"
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1 or re.search(r"\bto\b|\d\s*[-–]\s*\d", text):
        if re.fullmatch(r"\s*(?:1\s*)?dozen\s*", text):
            return {"quantity": 12.0, "unit": "count", "label": text.strip()}
        return None
    match = matches[0]
    count = int(match[1] or 1)
    quantity = Decimal(match[2]) * count
    unit = match[3]
    if unit.startswith(("kg", "kilogram")):
        quantity *= 1000
        base = "g"
    elif unit.startswith(("gm", "gram")) or unit == "g":
        base = "g"
    elif unit == "ml":
        base = "ml"
    elif unit.startswith(("lit", "ltr")) or unit == "l":
        quantity *= 1000
        base = "ml"
    else:
        base = "count"
    if quantity <= 0:
        return None
    return {"quantity": float(quantity), "unit": base, "label": match[0]}


def nutrition(value):
    """Preserve label text and basis. Parse numbers only with explicit units."""
    if not value:
        return None
    if isinstance(value, str):
        text = plain_text(value)
        basis_match = re.search(r"(?:per|serving size)\s*:?\s*(100\s*(?:g|ml)|[\d.]+\s*(?:g|ml)\b)", text, re.I)
        macros = {}
        if basis_match:
            for label, key in (("energy|calories", "energy"), ("protein", "protein"),
                               ("carbohydrates?", "carbohydrate"), ("total fat|fat", "fat"),
                               ("dietary fib(?:er|re)|fib(?:er|re)", "fiber"), ("sugars?", "sugar")):
                match = re.search(rf"\b(?:{label})\s*:?\s*([\d.,]+)\s*(kcal|kj|g|mg)\b", text, re.I)
                if match:
                    number = decimal_number(match[1])
                    if number is not None:
                        macros[key] = {"value": float(number), "unit": match[2].lower()}
        return {"raw_label": text, "basis": basis_match[1] if basis_match else None, "macros": macros}
    if not isinstance(value, dict):
        return {"raw_label": str(value), "basis": None, "macros": {}}
    macros = {}
    names = {"calories": "energy", "proteinContent": "protein", "carbohydrateContent": "carbohydrate",
             "fatContent": "fat", "fiberContent": "fiber", "sugarContent": "sugar", "sodiumContent": "sodium"}
    for field, name in names.items():
        match = re.fullmatch(r"\s*([\d.,]+)\s*(kcal|cal|kj|g|mg)\s*", str(value.get(field, "")), re.I)
        if match:
            number = decimal_number(match[1])
            if number is not None:
                macros[name] = {"value": float(number), "unit": match[2].lower()}
    return {"basis": value.get("servingSize"), "macros": macros, "source_fields": value}
