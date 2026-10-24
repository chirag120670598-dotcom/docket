"""Which CSIRT you actually file with — Article 14(7) of Regulation (EU) 2024/2847.

Almost every CRA summary in circulation stops at "report within 24 hours". It does
not say *to whom*. Article 14(7) is a cascade, and getting it wrong means the
24-hour clock runs out against the wrong authority, which is indistinguishable
from not reporting at all.

The rule, in the Regulation's own order:

  14(7) → the CSIRT of the Member State where the manufacturer has its **main
          establishment** in the Union. "Main establishment" means the Member
          State where the decisions related to the cybersecurity of the products
          with digital elements are predominantly taken. If that cannot be
          determined, the Member State where the manufacturer has the
          establishment with the highest number of employees in the Union.

  If the manufacturer has **no main establishment in the Union**, then:

    (a) the Member State where the **authorised representative** that acts on
        behalf of the manufacturer for the highest number of products is
        established;
    (b) failing that, the Member State where the **importer** that places the
        highest number of products on the market is established;
    (c) failing that, the Member State where the **distributor** that makes the
        highest number of products available on the market is established;
    (d) failing that, the Member State where the **highest number of users** of
        the product are located.

  And then the sentence that catches everyone: where (d) applies, the
  manufacturer **may submit subsequent notifications to the same CSIRT it first
  reported to**. Jurisdiction, once chosen by user base, sticks.

Anything reported on a guess is an assumption the user has to own, so this
module refuses to name a Member State unless the caller supplied enough to
decide — it returns the branch it took and the reasoning, and it names the
missing fact when it cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The 27 Member States, with the ISO 3166-1 alpha-2 code used on the report.
MEMBER_STATES: dict[str, str] = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia",
    "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia",
    "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece",
    "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LV": "Latvia",
    "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SK": "Slovakia",
    "SI": "Slovenia", "ES": "Spain", "SE": "Sweden",
}

BRANCHES = {
    "main_establishment": "Article 14(7), first subparagraph — main establishment",
    "employees": "Article 14(7), first subparagraph — highest number of employees",
    "representative": "Article 14(7)(a) — authorised representative",
    "importer": "Article 14(7)(b) — importer",
    "distributor": "Article 14(7)(c) — distributor",
    "users": "Article 14(7)(d) — highest number of users",
}


@dataclass
class Routing:
    """The outcome of Article 14(7) applied to a facts pattern."""

    state: str | None
    state_name: str | None
    branch: str | None
    reason: str
    missing: list[str] = field(default_factory=list)
    sticky: bool = False

    @property
    def resolved(self) -> bool:
        return self.state is not None

    def explain(self) -> str:
        if not self.resolved:
            asks = "; ".join(self.missing)
            return f"No CSIRT can be named yet. Missing: {asks}."
        out = f"File with the CSIRT of {self.state_name} ({self.state})."
        out += f"\nBasis: {BRANCHES[self.branch]}.\n{self.reason}"
        if self.sticky:
            out += ("\nNote: because jurisdiction was fixed by user location, "
                    "Article 14(7) lets you submit subsequent notifications to "
                    "this same CSIRT rather than re-deriving it each time.")
        return out


def route(
    *,
    main_establishment: str | None = None,
    employees_by_state: dict[str, int] | None = None,
    has_eu_establishment: bool = True,
    representative: tuple[str, int] | None = None,
    importer: tuple[str, int] | None = None,
    distributor: tuple[str, int] | None = None,
    users: tuple[str, int] | None = None,
) -> Routing:
    """Apply Article 14(7) in its stated order.

    Every tuple is ``(ISO state code, count of products or users)``.
    """

    def norm(code: str) -> str:
        c = code.strip().upper()[:2]
        if c not in MEMBER_STATES:
            raise ValueError(f"{code!r} is not an EU Member State code")
        return c

    if has_eu_establishment:
        if main_establishment:
            c = norm(main_establishment)
            return Routing(
                c, MEMBER_STATES[c], "main_establishment",
                "The decisions on the cybersecurity of the product are "
                "predominantly taken in this Member State.",
            )
        if employees_by_state:
            valid = {norm(k): v for k, v in employees_by_state.items() if v > 0}
            if valid:
                c = max(valid, key=lambda k: (valid[k], k))
                return Routing(
                    c, MEMBER_STATES[c], "employees",
                    f"Main establishment could not be determined, so the "
                    f"establishment with the highest number of employees "
                    f"in the Union decides it ({valid[c]} employees).",
                )
        return Routing(
            None, None, None,
            "The manufacturer is established in the Union, so the first "
            "subparagraph of Article 14(7) applies — but neither the place "
            "where cybersecurity decisions are taken nor the employee "
            "headcount by Member State was supplied.",
            missing=["Member State where cybersecurity decisions are taken",
                     "or employee headcount by Member State"],
        )

    for label, pair, branch in (
        ("authorised representative", representative, "representative"),
        ("importer", importer, "importer"),
        ("distributor", distributor, "distributor"),
        ("user base", users, "users"),
    ):
        if pair and pair[1] > 0:
            c = norm(pair[0])
            reason = (
                f"No main establishment in the Union, and no closer qualifying "
                f"{label} was supplied, so the Member State of the {label} "
                f"handling the highest number of products governs "
                f"({pair[1]})."
            )
            return Routing(c, MEMBER_STATES[c], branch, reason,
                           sticky=(branch == "users"))

    return Routing(
        None, None, None,
        "No main establishment in the Union and no authorised representative, "
        "importer, distributor or user-location data was supplied, so none of "
        "the Article 14(7)(a)–(d) limbs can be satisfied.",
        missing=["authorised representative in the Union (or importer, "
                 "distributor, or user locations)"],
    )
