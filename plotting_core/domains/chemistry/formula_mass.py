"""Audit numeric formula counts and use a versioned CIAAW abridged mass table."""

import copy
import hashlib
import json
import math
from pathlib import Path
import re

from ...ingest.report import ValidationReport

TABLE_PATH = Path(__file__).resolve().with_name("atomic_weights_ciaaw2024_abridged.json")
_NUMBER = re.compile(r"(?:\d+(?:\.\d+)?|\.\d+)")
_ELEMENT = re.compile(r"[A-Z][a-z]?")


def load_atomic_weights():
    """Return an independent JSON record; symbols are exact and case-sensitive."""
    with TABLE_PATH.open("r", encoding="utf-8") as handle:
        table = json.load(handle)
    table["sha256"] = hashlib.sha256(TABLE_PATH.read_bytes()).hexdigest()
    return table


def atomic_weight(symbol, report=None, context="element"):
    """Return standard atomic-weight numeric value or None with a question.

    Its numeric value is used conventionally as g/mol. No element aliases,
    isotope masses, missing standard weights, or capitalization are guessed.
    """
    if report is None:
        report = ValidationReport()
    table = load_atomic_weights()
    if not isinstance(symbol, str) or symbol not in table["elements"]:
        report.question("%s: element symbol %r has no supported CIAAW2024 standard atomic weight; confirm exact symbol/isotopic or material basis" % (context, symbol))
        return None
    return table["elements"][symbol]["atomic_weight"]


class _Parser:
    def __init__(self, text, table, report, context):
        self.text, self.table, self.report, self.context = text, table, report, context
        self.position = 0

    def question(self, message):
        self.report.question("%s at character %d: %s" % (self.context, self.position + 1, message))

    def number(self):
        match = _NUMBER.match(self.text, self.position)
        if match is None:
            return 1.0
        self.position = match.end()
        value = float(match.group())
        if not math.isfinite(value) or value <= 0:
            self.question("stoichiometric coefficients must be finite and positive; zero/negative terms need an explicitly simplified formula")
        return value

    def group(self, nested=False):
        counts, terms = {}, 0
        while self.position < len(self.text):
            char = self.text[self.position]
            if char == ")":
                if not nested:
                    self.question("unmatched closing parenthesis")
                self.position += 1
                return counts, terms
            if char == "(":
                self.position += 1
                inner, inner_terms = self.group(nested=True)
                if not inner_terms:
                    self.question("empty parentheses do not define a formula")
                multiplier = self.number()
                for symbol, count in inner.items():
                    counts[symbol] = counts.get(symbol, 0.0) + count * multiplier
                terms += inner_terms
                continue
            match = _ELEMENT.match(self.text, self.position)
            if match:
                symbol = match.group()
                self.position = match.end()
                count = self.number()
                if symbol not in self.table["elements"]:
                    self.question("unknown element or no supported standard atomic weight for %s" % symbol)
                counts[symbol] = counts.get(symbol, 0.0) + count
                terms += 1
                continue
            self.question("unsupported token %r; variable coefficients, isotope labels and charges require explicit clarification" % char)
            self.position += 1
        if nested:
            self.question("missing closing parenthesis")
        return counts, terms


def calculate_formula_mass(formula, report=None, context="formula"):
    """Return counts, contributions and M, aggregating unsupported notation.

    Numeric decimal stoichiometry, nested parentheses and middle-dot hydrate
    factors are supported. Leading numbers in the initial segment are rejected
    because isotope labels and overall multipliers cannot be distinguished safely.
    Neither a material identity nor an unknown x/delta occupancy is inferred.
    """
    if report is None:
        report = ValidationReport()
    before = len(report.errors) + len(report.questions)
    table = load_atomic_weights()
    metadata = {key: copy.deepcopy(value) for key, value in table.items() if key != "elements"}
    counts = {}
    if not isinstance(formula, str) or not formula.strip():
        report.question("%s requires a known non-empty numeric chemical formula" % context)
        text = ""
    else:
        text = formula.strip().translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
        if any(char.isspace() for char in text):
            report.question("%s contains internal whitespace; supply an unambiguous compact numeric formula" % context)
        if any(char in text for char in ("[", "]", "^", "+", "-", "−")):
            report.question("%s: isotope labels/charges/signed variable coefficients are not supported; clarify numeric neutral formula and mass basis" % context)
        parts = re.split("[·∙]", text)
        if re.search(r"\d*\.\d+H2O$", parts[0]):
            report.question("%s has an ambiguous ASCII decimal dot before H2O; use an explicit middle dot for a hydrate, or explicit parentheses for fractional stoichiometry" % context)
        for index, part in enumerate(parts):
            if not part:
                report.question("%s has an empty hydrate/adduct segment" % context)
                continue
            parser = _Parser(part, table, report, "%s segment %d" % (context, index + 1))
            factor = 1.0
            if _NUMBER.match(part):
                if index == 0:
                    report.question("%s begins with a number; isotope labels/whole-formula coefficients require explicit clarification" % context)
                factor = parser.number()
                if index > 0 and part[parser.position:] not in ("H2O", "(H2O)"):
                    report.question("%s: a numeric leading adduct coefficient outside explicit H2O is ambiguous with an isotope label; clarify its formula-unit interpretation" % context)
            part_counts, terms = parser.group()
            if parser.position != len(part):
                report.question("%s has trailing tokens after a parenthesis" % context)
            if not terms:
                report.question("%s segment %d contains no supported element formula" % (context, index + 1))
            for symbol, count in part_counts.items():
                counts[symbol] = counts.get(symbol, 0.0) + count * factor
    valid = len(report.errors) + len(report.questions) == before and bool(counts)
    contributions = []
    mass = 0.0
    if valid:
        for symbol in sorted(counts):
            entry = table["elements"][symbol]
            contribution = counts[symbol] * entry["atomic_weight"]
            if not math.isfinite(counts[symbol]) or not math.isfinite(contribution):
                report.question("%s has non-finite formula counts/mass; no mass is produced" % context)
                valid = False
                break
            mass += contribution
            contributions.append({"symbol": symbol, "count": counts[symbol],
                                  "atomic_weight": entry["atomic_weight"],
                                  "atomic_weight_uncertainty": entry["uncertainty"],
                                  "contribution_g_mol": contribution})
        if not math.isfinite(mass) or mass <= 0:
            report.question("%s has no finite positive molar mass" % context)
            valid = False
    return {"ready": valid, "formula": formula, "normalized_formula": text, "element_counts": counts,
            "molar_mass_g_mol": mass if valid else None, "contributions": contributions,
            "table": metadata, "scientific_truth_verified": False,
            "interpretation": "conventional formula molar mass from normal-material standard atomic weights; isotopic/material identity not independently verified",
            "report": report.to_dict()}
