"""Stage 2: from a located defect to an upstream SMT fault.

The rule table always produces a diagnosis. An LLM may re-rank and reword it, but
pass/fail and defect class stay with the code, and any invalid reply falls back to
the rule output.
"""
from __future__ import annotations

import json
from typing import Callable

from pydantic import ValidationError

from .schemas import Defect, Diagnosis, Hypothesis

LlmCall = Callable[[str, dict], dict]

RULES: dict[str, list[tuple[str, str, str, str, float]]] = {
    "solder_bridge": [
        ("Stencil printing", "Stencil Squeegee Pressure", "Paste joined adjacent fine-pitch pads", "Check squeegee pressure and wipe the stencil underside", 0.6),
        ("Stencil printing", "Stencil aperture or gasket wear", "Excess paste volume at fine pitch", "Inspect apertures and review SPI paste volume on this footprint", 0.3),
    ],
    "tombstoning": [
        ("Reflow", "Reflow Thermal Zone Ramp Rate", "Uneven wetting force lifted one end of a small two-terminal part", "Reduce preheat ramp and check zone balance across the part", 0.6),
        ("Pick-and-place", "Placement offset on the pads", "An off-centre part wets one pad first", "Check placement offset for this feeder", 0.25),
    ],
    "missing_component": [
        ("Pick-and-place", "Pick-and-Place Nozzle Vacuum Leak", "Pads carry no part and no reflowed joint", "Check nozzle vacuum and pick-up errors on this feeder", 0.6),
        ("Pick-and-place", "Feeder empty or mis-indexed", "Single position missing", "Check reel and feeder pitch for this part", 0.3),
    ],
    "polarity_error": [
        ("Pick-and-place", "Reel loaded or programmed with wrong orientation", "Polarity band sits at the opposite end", "Verify the feeder angle in the placement program against the reel", 0.65),
        ("Hand assembly", "Manual placement or rework", "Single board reversed", "Check recent manual touch-up on this board", 0.2),
    ],
    "bga_voiding": [
        ("Reflow", "Reflow Soak Profile Too Short", "Flux volatiles were trapped under the thermal pad", "Lengthen soak and review peak time above liquidus", 0.55),
        ("Stencil printing", "Thermal pad aperture too open", "Large continuous paste deposit traps gas", "Use a window-pane aperture on the thermal pad", 0.3),
    ],
    "unclassified_anomaly": [
        ("Inspection", "Unrecognised difference from golden board", "Region differs from the reference", "Route to a QA engineer for visual review", 0.3),
    ],
}
RULES["insufficient_solder"] = [("Stencil printing", "Clogged aperture or low paste volume", "Joint has too little solder", "Clean the stencil and check SPI volume", 0.5)]
RULES["excess_solder"] = [("Stencil printing", "Excess paste deposit", "Joint has too much solder", "Check stencil thickness and print alignment", 0.5)]
RULES["cold_joint"] = [("Reflow", "Peak temperature too low", "Joint looks dull and did not fully wet", "Measure the profile with a thermocouple on this zone", 0.5)]

INSTRUCTIONS: dict[str, str] = {
    "solder_bridge": "Solder bridge on {ref} between pins {pins}. Apply no-clean flux, set the iron to 350°C, and draw the bridge away with 1.5 mm copper braid. Clean the area and check the gap under the microscope.",
    "tombstoning": "{ref} is standing on one end. Apply flux, heat both pads with the iron at 340°C, remove the part, clean the pads with braid, and solder a new part flat on both pads.",
    "missing_component": "{ref} is missing. Check the BOM for the correct value, add fresh solder paste or flux to both pads, place the part, and solder both ends.",
    "polarity_error": "{ref} is fitted the wrong way round. Remove it with hot air at 340°C, clean the pads, and refit it with the band on the side marked on the silkscreen.",
    "bga_voiding": "{ref} thermal pad has {void}% voiding, above the {limit}% limit. Do not rework by hand. Hold this board and send it to the BGA rework station for reball and X-ray recheck.",
    "unclassified_anomaly": "Unknown difference found near {ref}. Do not touch the board. Call the QA engineer for a visual check.",
    "insufficient_solder": "{ref} has too little solder. Apply flux and add solder until the joint forms a smooth fillet.",
    "excess_solder": "{ref} has too much solder. Apply flux and remove the extra with copper braid.",
    "cold_joint": "{ref} has a cold joint. Apply flux and reflow the joint with the iron at 350°C.",
}

LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "process_stage": {"type": "string"},
                "fault": {"type": "string"},
                "evidence": {"type": "string"},
                "corrective_action": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["process_stage", "fault", "evidence", "corrective_action", "confidence"],
            "additionalProperties": False,
        }},
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You assist a process engineer in an SMT line at an EMS factory. The board has already failed "
    "and the defect class is final. You get the defect, its BOM location, how often it recurred, and "
    "candidate upstream faults. Rank the candidates, adjust confidence, and tighten the evidence using "
    "only the facts given. Keep fault names unchanged. Write in English."
)


def diagnose_rules(defect: Defect, recurrence: int = 0, void_pct: float | None = None, limit_pct: float = 25.0) -> Diagnosis:
    rows = RULES[defect.defect_class]
    boost = min(0.2, 0.05 * recurrence) if recurrence else 0.0
    hypotheses = [
        Hypothesis(process_stage=s, fault=f, corrective_action=a,
                   evidence=e + (f"; seen {recurrence} earlier time(s) at this location" if recurrence and i == 0 else ""),
                   confidence=round(min(0.95, c + (boost if i == 0 else 0)), 2))
        for i, (s, f, e, a, c) in enumerate(rows)
    ]
    ref = defect.bom.designator if defect.bom else "this area"
    pins = " and ".join(str(p) for p in defect.bom.pins[:4]) if defect.bom else ""
    instruction = INSTRUCTIONS[defect.defect_class].format(ref=ref, pins=pins, void=void_pct, limit=limit_pct)
    return Diagnosis(designator=defect.bom.designator if defect.bom else None, defect_class=defect.defect_class,
                     hypotheses=hypotheses, rework_instruction_en=instruction)


def diagnose(defect: Defect, llm: LlmCall | None = None, recurrence: int = 0,
             void_pct: float | None = None, limit_pct: float = 25.0) -> Diagnosis:
    base = diagnose_rules(defect, recurrence, void_pct, limit_pct)
    if llm is None:
        return base
    payload = json.dumps({
        "defect": defect.model_dump(include={"defect_class", "bom"}),
        "recurrence": recurrence,
        "void_pct": void_pct,
        "candidates": [h.model_dump() for h in base.hypotheses],
    })
    try:
        reply = llm(SYSTEM_PROMPT, {"payload": payload, "schema": LLM_SCHEMA})
        hypotheses = [Hypothesis.model_validate(h) for h in reply["hypotheses"]]
    except (ValidationError, KeyError, TypeError, ValueError, OSError, RuntimeError):
        return base
    allowed = {h.fault for h in base.hypotheses}
    hypotheses = [h for h in hypotheses if h.fault in allowed]
    if not hypotheses:
        return base
    return base.model_copy(update={"hypotheses": hypotheses, "source": "llm"})
