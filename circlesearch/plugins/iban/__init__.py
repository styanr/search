import re
from dataclasses import dataclass, field

from circlesearch.core.cards import Action, Card
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer

LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29, "BY": 28,
    "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18,
    "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22,
    "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20,
    "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SC": 31, "SE": 24, "SI": 19,
    "SK": 24, "SM": 27, "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}
COUNTRIES = {
    "AD": "Andorra", "AE": "United Arab Emirates", "AL": "Albania", "AT": "Austria", "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina", "BE": "Belgium", "BG": "Bulgaria", "BH": "Bahrain", "BR": "Brazil",
    "BY": "Belarus", "CH": "Switzerland", "CR": "Costa Rica", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany",
    "DK": "Denmark", "DO": "Dominican Republic", "EE": "Estonia", "EG": "Egypt", "ES": "Spain", "FI": "Finland",
    "FO": "Faroe Islands", "FR": "France", "GB": "United Kingdom", "GE": "Georgia", "GI": "Gibraltar",
    "GL": "Greenland", "GR": "Greece", "GT": "Guatemala", "HR": "Croatia", "HU": "Hungary", "IE": "Ireland",
    "IL": "Israel", "IQ": "Iraq", "IS": "Iceland", "IT": "Italy", "JO": "Jordan", "KW": "Kuwait", "KZ": "Kazakhstan",
    "LB": "Lebanon", "LC": "Saint Lucia", "LI": "Liechtenstein", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "MC": "Monaco", "MD": "Moldova", "ME": "Montenegro", "MK": "North Macedonia",
    "MR": "Mauritania", "MT": "Malta", "MU": "Mauritius", "NL": "Netherlands", "NO": "Norway", "PK": "Pakistan",
    "PL": "Poland", "PS": "Palestine", "PT": "Portugal", "QA": "Qatar", "RO": "Romania", "RS": "Serbia",
    "SA": "Saudi Arabia", "SC": "Seychelles", "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia",
    "SM": "San Marino", "ST": "São Tomé and Príncipe", "SV": "El Salvador", "TL": "Timor-Leste", "TN": "Tunisia",
    "TR": "Türkiye", "UA": "Ukraine", "VA": "Vatican City", "VG": "British Virgin Islands", "XK": "Kosovo",
}
BANK_CODE = {"UA": (4, 10), "GB": (4, 8), "DE": (4, 12), "PL": (4, 8), "AT": (4, 9), "CH": (4, 9), "NL": (4, 8),
             "FR": (4, 9), "ES": (4, 8), "IT": (5, 10), "BE": (4, 7), "LT": (4, 9), "LV": (4, 8), "EE": (4, 6),
             "CZ": (4, 8), "SK": (4, 8), "HU": (4, 7), "RO": (4, 8), "BG": (4, 8), "IE": (4, 8), "PT": (4, 8),
             "FI": (4, 7), "SE": (4, 7), "DK": (4, 8), "NO": (4, 8), "HR": (4, 11), "SI": (4, 9), "GE": (4, 6),
             "MD": (4, 6), "KZ": (4, 7), "TR": (4, 9), "CY": (4, 7), "LU": (4, 7), "GR": (4, 7)}
UA_BANKS = {
    "305299": "PrivatBank", "322001": "Universal Bank (monobank)", "300465": "Oschadbank",
    "380805": "Raiffeisen Bank", "351005": "UKRSIBBANK", "334851": "PUMB", "322313": "Ukreximbank",
    "307770": "A-Bank", "300528": "OTP Bank", "300346": "Sense Bank", "300614": "Credit Agricole Bank",
    "320478": "Ukrgasbank", "328209": "Pivdennyi Bank", "325365": "Kredobank", "320984": "ProCredit Bank",
    "339500": "TASCOMBANK", "336310": "Idea Bank", "380838": "Pravex Bank", "300584": "Citibank Ukraine",
    "820172": "State Treasury Service of Ukraine",
}
GB_BANKS = {"NWBK": "NatWest", "BARC": "Barclays", "HBUK": "HSBC UK", "MIDL": "HSBC", "LOYD": "Lloyds Bank",
            "RBOS": "Royal Bank of Scotland", "MONZ": "Monzo", "SRLG": "Starling Bank", "REVO": "Revolut",
            "CITI": "Citibank", "BUKB": "Barclays", "ABBY": "Santander UK", "TSBS": "TSB Bank"}
PL_BANKS = {"1020": "PKO Bank Polski", "1050": "ING Bank Śląski", "1090": "Santander Bank Polska",
            "1140": "mBank", "1240": "Bank Pekao", "1160": "Bank Millennium", "2490": "Alior Bank"}
CONFUSABLE = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7"}
IBAN = re.compile(r"^(?:IBAN[:\s]*)?([A-Z]{2}\s?\d{2}(?:\s?[A-Z0-9]){10,30})$", re.I)


@dataclass(kw_only=True)
class IbanCard(Card):
    kind = "iban"
    accent = "green"
    priority = 2

    iban: str
    valid: bool
    status: str
    country: str = ""
    bank: str = ""
    rows: list[tuple[str, str]] = field(default_factory=list)
    suggestion: str = ""


def compact(text):
    return re.sub(r"[\s-]", "", text).upper().removeprefix("IBAN").lstrip(":")


def checksum(iban):
    moved = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in moved)
    return int(digits) % 97


def check_digits(iban):
    probe = iban[:2] + "00" + iban[4:]
    return f"{98 - checksum(probe):02d}"


def valid(iban):
    return len(iban) == LENGTHS.get(iban[:2], -1) and iban[2:4].isdigit() and checksum(iban) == 1


def grouped(iban):
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def repair(iban):
    if not iban[2:4].isdigit() and all(ch in CONFUSABLE or ch.isdigit() for ch in iban[2:4]):
        iban = iban[:2] + "".join(CONFUSABLE.get(ch, ch) for ch in iban[2:4]) + iban[4:]
    if valid(iban):
        return iban
    numeric = iban[:2] in ("UA", "DE", "PL", "BE", "CZ", "SK", "DK", "FI", "NO", "SE", "HU", "EE", "LT", "SI", "TR",
                           "HR", "RS", "AT", "ES", "PT", "RO")
    if numeric:
        candidate = iban[:4] + "".join(CONFUSABLE.get(ch, ch) for ch in iban[4:])
        if candidate != iban and valid(candidate):
            return candidate
    return None


def bank_name(iban):
    country = iban[:2]
    span = BANK_CODE.get(country)
    if not span:
        return "", ""
    code = iban[span[0]:span[1]]
    table = {"UA": UA_BANKS, "GB": GB_BANKS, "PL": PL_BANKS}.get(country, {})
    return code, table.get(code, "")


@recognizer("iban", order=35, max_chars=60)
def parse_iban(text):
    m = IBAN.match(text.strip())
    if not m:
        return None
    iban = compact(m.group(1))
    if iban[:2] not in LENGTHS or not 15 <= len(iban) <= 34:
        return None
    if len(iban) != LENGTHS[iban[:2]]:
        return iban if abs(len(iban) - LENGTHS[iban[:2]]) <= 2 else None
    return iban


def describe(iban):
    country = iban[:2]
    expected = LENGTHS.get(country)
    rows = []
    code, bank = bank_name(iban)
    suggestion = ""
    if len(iban) != expected:
        ok, status = False, f"Wrong length, {len(iban)} of {expected}"
    elif valid(iban):
        ok, status = True, "Valid"
    else:
        ok = False
        fixed = repair(iban)
        if fixed:
            suggestion = fixed
            status = "Invalid check digits"
        else:
            status = "Invalid check digits"
    rows.append(("Country", COUNTRIES.get(country, country)))
    if bank:
        rows.append(("Bank", bank))
    if code:
        rows.append(("MFO" if country == "UA" else "Bank code", code))
    if country == "UA" and len(iban) == 29:
        rows.append(("Account", iban[10:].lstrip("0") or "0"))
    return ok, status, COUNTRIES.get(country, country), bank, rows, suggestion


@resolver("iban")
def iban_card(route):
    iban = route.value
    ok, status, country, bank, rows, suggestion = describe(iban)
    actions = [Action("Copy IBAN", "copy", iban), Action("With spaces", "copy", grouped(iban))]
    if suggestion:
        actions.insert(0, Action("Copy corrected", "copy", suggestion))
    return IbanCard(title=grouped(iban), iban=iban, valid=ok, status=status, country=country, bank=bank, rows=rows,
                    suggestion=grouped(suggestion) if suggestion else "", actions=actions)
