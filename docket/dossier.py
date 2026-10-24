"""Article 14 filing dossiers for the Cyber Resilience Act.

The obligation is not "write a report". It is three reports against three
different clocks, each with a prescribed minimum content, and the content
requirements differ between the vulnerability path (Article 14(2)) and the
severe-incident path (Article 14(4)). This module holds the field lists
straight from the Regulation, checks a draft against them, and emits the
dossier in a form that can be pasted into the ENISA single reporting platform.

The clocks:

    vulnerability   early warning            +24 h from awareness   14(2)(a)
                    vulnerability notice     +72 h from awareness   14(2)(b)
                    final report             +14 d after a fix      14(2)(c)

    severe          early warning            +24 h from awareness   14(4)(a)
      incident      incident notification    +72 h from awareness   14(4)(b)
                    final report             +1 month after the     14(4)(c)
                                               incident notification
                                               was submitted

The distinction that matters and is usually missed: the vulnerability final
report is anchored to the moment a *fix exists*; the incident final report is
anchored to the moment the *notification was submitted*. Different anchors,
different dates.

Field names below are paraphrases of the Regulation's wording, kept short for a
form. The ``cite`` on each field is the provision it comes from, so a reviewer
can check any single line against the text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from .routing import Routing


class Path(str, Enum):
    VULNERABILITY = "vulnerability"
    INCIDENT = "incident"


class Stage(str, Enum):
    EARLY_WARNING = "early_warning"
    NOTIFICATION = "notification"
    FINAL = "final"


# --------------------------------------------------------------------------
# Content requirements, taken from the Regulation itself.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Requirement:
    key: str
    label: str
    cite: str
    required: bool = True
    # "as available" fields may legitimately be empty at the early stages — the
    # Regulation says "general information available" rather than demanding it.
    as_available: bool = False

    def describe(self) -> str:
        mark = "required" if self.required else ("if available" if self.as_available else "optional")
        return f"{self.label} [{mark}, {self.cite}]"


REQUIREMENTS: dict[tuple[Path, Stage], list[Requirement]] = {
    (Path.VULNERABILITY, Stage.EARLY_WARNING): [
        Requirement("product_identification", "Product or product category affected", "14(2)(a)"),
        Requirement("vulnerability_suspected", "Indication that the product is suspected of being affected by an actively exploited vulnerability", "14(2)(a)"),
        Requirement("member_states_aware", "Member States where the affected product has been made available, where applicable", "14(2)(a)", required=False),
    ],
    (Path.VULNERABILITY, Stage.NOTIFICATION): [
        Requirement("product_information", "General information on the product with digital elements", "14(2)(b)(i)", as_available=True),
        Requirement("exploit_nature", "General nature of the exploit", "14(2)(b)(ii)", as_available=True),
        Requirement("vulnerability_nature", "General nature of the vulnerability", "14(2)(b)(iii)", as_available=True),
        Requirement("measures_taken", "Any corrective or mitigating measures taken", "14(2)(b)(iv)", as_available=True),
        Requirement("measures_for_users", "Corrective or mitigating measures users can take", "14(2)(b)(v)", as_available=True),
        Requirement("sensitivity", "How sensitive the manufacturer considers the information to be", "14(2)(b)(vi)", required=False),
    ],
    (Path.VULNERABILITY, Stage.FINAL): [
        Requirement("vulnerability_description", "Detailed description of the vulnerability, including its severity and impact", "14(2)(c)(i)"),
        Requirement("malicious_actor", "Information on any malicious actor exploiting the vulnerability, where available", "14(2)(c)(ii)", as_available=True),
        Requirement("remedy_details", "Details of the security update or other corrective measures made available", "14(2)(c)(iii)"),
    ],
    (Path.INCIDENT, Stage.EARLY_WARNING): [
        Requirement("product_identification", "Product or product category affected", "14(4)(a)"),
        Requirement("suspected_malicious", "Whether the incident is suspected of being caused by unlawful or malicious acts", "14(4)(a)"),
        Requirement("member_states_aware", "Member States where the product has been made available, where applicable", "14(4)(a)", required=False),
    ],
    (Path.INCIDENT, Stage.NOTIFICATION): [
        Requirement("incident_nature", "General information on the nature of the incident", "14(4)(b)(i)", as_available=True),
        Requirement("initial_assessment", "Initial assessment of the incident's severity and impact", "14(4)(b)(ii)", as_available=True),
        Requirement("measures_taken", "Any corrective or mitigating measures taken", "14(4)(b)(iii)", as_available=True),
        Requirement("measures_for_users", "Corrective or mitigating measures users can take", "14(4)(b)(iv)", as_available=True),
        Requirement("sensitivity", "How sensitive the manufacturer considers the information to be", "14(4)(b)(v)", required=False),
    ],
    (Path.INCIDENT, Stage.FINAL): [
        Requirement("incident_description", "Detailed description of the incident, including its severity and impact", "14(4)(c)(i)"),
        Requirement("root_cause", "Type of threat or root cause likely to have triggered the incident", "14(4)(c)(ii)"),
        Requirement("mitigation_applied", "Applied and ongoing mitigation measures", "14(4)(c)(iii)"),
    ],
}

# Article 14(5): what makes an incident "severe". The user has to answer this
# before the incident path is even available to them.
SEVERE_TEST = [
    ("data_integrity",
     "Negatively affects or is capable of negatively affecting the ability to "
     "protect the availability, authenticity, integrity or confidentiality of "
     "sensitive or important data or functions"),
    ("malicious_code",
     "Has led or is capable of leading to the introduction or execution of "
     "malicious code"),
]


@dataclass
class Clock:
    stage: Stage
    due: datetime
    basis: str

    @property
    def hours_left(self) -> float:
        return (self.due - datetime.now(timezone.utc)).total_seconds() / 3600

    @property
    def is_overdue(self) -> bool:
        return self.hours_left < 0

    def human(self) -> str:
        h = self.hours_left
        if h < 0:
            return f"OVERDUE by {abs(h):.1f} h"
        if h < 48:
            return f"due in {h:.1f} h"
        return f"due in {h / 24:.1f} days"


def schedule(
    path: Path,
    aware_at: datetime,
    *,
    fix_available_at: datetime | None = None,
    notification_sent_at: datetime | None = None,
) -> list[Clock]:
    """The three clocks for a given path, anchored as the Regulation anchors them."""
    if aware_at.tzinfo is None:
        aware_at = aware_at.replace(tzinfo=timezone.utc)

    out = [
        Clock(Stage.EARLY_WARNING, aware_at + timedelta(hours=24),
              "Article 14(2)(a)" if path is Path.VULNERABILITY else "Article 14(4)(a)"),
        Clock(Stage.NOTIFICATION, aware_at + timedelta(hours=72),
              "Article 14(2)(b)" if path is Path.VULNERABILITY else "Article 14(4)(b)"),
    ]

    if path is Path.VULNERABILITY:
        if fix_available_at is not None:
            fix = fix_available_at
            if fix.tzinfo is None:
                fix = fix.replace(tzinfo=timezone.utc)
            out.append(Clock(Stage.FINAL, fix + timedelta(days=14),
                             "Article 14(2)(c) — 14 days after a corrective or "
                             "mitigating measure is available"))
    else:
        anchor = notification_sent_at or (aware_at + timedelta(hours=72))
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        out.append(Clock(Stage.FINAL, anchor + timedelta(days=30),
                         "Article 14(4)(c) — one month after the incident "
                         "notification was submitted"
                         + ("" if notification_sent_at
                            else " (assumes submission at the 72-hour mark)")))
    return out


@dataclass
class Draft:
    """A worked example of a dossier being assembled."""

    path: Path
    stage: Stage
    product: str
    manufacturer: str
    facts: dict[str, str] = field(default_factory=dict)

    def gaps(self) -> list[Requirement]:
        return [r for r in REQUIREMENTS[(self.path, self.stage)]
                if r.required and not self.facts.get(r.key)]

    def completeness(self) -> float:
        reqs = REQUIREMENTS[(self.path, self.stage)]
        hard = [r for r in reqs if r.required]
        if not hard:
            return 1.0
        return sum(1 for r in hard if self.facts.get(r.key)) / len(hard)

    def as_json(self, routing: Routing | None = None) -> dict:
        payload = {
            "regulation": "Regulation (EU) 2024/2847",
            "provision": f"Article 14({'2' if self.path is Path.VULNERABILITY else '4'})"
                         f"{ {'early_warning': '(a)', 'notification': '(b)', 'final': '(c)'}[self.stage.value] }",
            "path": self.path.value,
            "stage": self.stage.value,
            "manufacturer": self.manufacturer,
            "product": self.product,
            "fields": {},
            "gaps": [r.key for r in self.gaps()],
            "completeness": round(self.completeness(), 3),
        }
        for r in REQUIREMENTS[(self.path, self.stage)]:
            if self.facts.get(r.key):
                payload["fields"][r.key] = {
                    "value": self.facts[r.key],
                    "cite": r.cite,
                }
        if routing is not None:
            payload["addressee"] = {
                "member_state": routing.state,
                "member_state_name": routing.state_name,
                "basis": routing.branch,
            }
        return payload

    def as_markdown(self, routing: Routing | None = None) -> str:
        stage_title = {
            Stage.EARLY_WARNING: "Early warning",
            Stage.NOTIFICATION: "Notification",
            Stage.FINAL: "Final report",
        }[self.stage]
        prov = "14(2)" if self.path is Path.VULNERABILITY else "14(4)"
        lines = [
            f"# {stage_title} — {self.path.value.title()}",
            "",
            f"**Instrument:** Regulation (EU) 2024/2847, Article {prov}"
            f"{ {'early_warning': '(a)', 'notification': '(b)', 'final': '(c)'}[self.stage.value] }",
            f"**Manufacturer:** {self.manufacturer}",
            f"**Product:** {self.product}",
        ]
        if routing is not None and routing.resolved:
            lines.append(f"**Addressee:** CSIRT of {routing.state_name} ({routing.state}) "
                         f"— {routing.branch}")
        elif routing is not None:
            lines.append("**Addressee:** not yet determinable — see Article 14(7) notes below")
        lines += ["", "## Content required by the provision", ""]
        for r in REQUIREMENTS[(self.path, self.stage)]:
            value = self.facts.get(r.key)
            if value:
                lines.append(f"- **{r.label}** _{r.cite}_  \n  {value}")
            else:
                tag = "MISSING" if r.required else ("not provided" if r.as_available else "optional")
                lines.append(f"- **{r.label}** _{r.cite}_  \n  — {tag}")
        if routing is not None:
            lines += ["", "## Addressee and jurisdiction", "", routing.explain()]
        lines += [
            "",
            "---",
            "Prepared with Docket. This dossier is a record of what you supplied "
            "against the provision's own field list. It is not a legal "
            "assessment of whether the discharge of the duty was adequate, and "
            "it is not a filing: the report itself must be submitted through "
            "the ENISA single reporting platform.",
        ]
        return "\n".join(lines)

    def as_text(self) -> str:
        return json.dumps(self.as_json(), indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------
# Worked example. Constructed from public facts about a fictional product so
# that the shape of a real filing is visible; every field is labelled.
# --------------------------------------------------------------------------

def example_dossier() -> Draft:
    return Draft(
        path=Path.VULNERABILITY,
        stage=Stage.NOTIFICATION,
        product="Acme Hub 3000 — firmware 4.2.1 and earlier "
                "(connected building controller)",
        manufacturer="Acme Controls GmbH",
        facts={
            "product_information":
                "Acme Hub 3000 running firmware 4.1.0 through 4.2.1. "
                "Distributed in DE, FR, NL, PL and ES through two distributors.",
            "exploit_nature":
                "Authentication bypass in the local management interface, "
                "reachable on the LAN. Exploitation is observed as a crafted "
                "session cookie that skips the password check.",
            "vulnerability_nature":
                "Improper verification of the session token's HMAC. "
                "An attacker who has already obtained a signed token for any "
                "account can alter the account identifier and retain validity.",
            "measures_taken":
                "Vulnerable endpoint disabled server-side via the fleet "
                "management channel for enrolled devices. Firmware fix in "
                "validation.",
            "measures_for_users":
                "Block inbound access to the management interface from "
                "untrusted VLANs until firmware 4.2.2 is installed. Enrol the "
                "device in fleet management to receive the remote disable.",
            "sensitivity":
                "Manufacturer considers this information sensitive until "
                "firmware 4.2.2 is generally available.",
        },
    )
