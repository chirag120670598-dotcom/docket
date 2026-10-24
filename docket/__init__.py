"""Docket — the CRA Article 14 clock and filing dossier.

Two things ship here:

* ``docket.dossier`` turns a description of an event into the exact field list
  Article 14 requires, on the exact clocks Article 14 sets.
* ``docket.routing`` answers the question the summaries skip: which CSIRT.

Ported from the ``hourglass`` engine, which the same author built for the
24/72-hour clock alone. Docket keeps that clock and adds the part that costs
people money — the addressee and the filing content.
"""

from .dossier import (
    REQUIREMENTS,
    SEVERE_TEST,
    Clock,
    Draft,
    Path,
    Stage,
    example_dossier,
    schedule,
)
from .routing import MEMBER_STATES, Routing, route

__version__ = "1.0.0"

__all__ = [
    "REQUIREMENTS", "SEVERE_TEST", "Clock", "Draft", "Path", "Stage",
    "example_dossier", "schedule", "MEMBER_STATES", "Routing", "route",
    "__version__",
]
