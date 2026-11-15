"""Auditable probability helpers for SimpleFortChest."""
from __future__ import annotations

import math

BASE_TOKEN_DENOMINATOR = 137_500

REWARD_ODDS = (
    ("Pirate Shop Access", 137_500),
    ("Atuendo dorado semanal", 1_562_500),
    ("Vehículo y decal semanal", 7_813),
    ("Pico o accesorio semanal", 568),
    ("Jam Track semanal", 391),
    ("Pantalla de carga semanal", 272),
    ("Cualquier Gizmo", 127),
)


def per_chest_probability(denominator: int, multiplier: float = 1.0) -> float:
    """Return the chance for one opening, clamped to the valid probability range."""
    if denominator <= 0 or multiplier <= 0:
        raise ValueError("denominator and multiplier must be positive")
    return min(1.0, multiplier / denominator)


def chance_at_least_one(
    attempts: int, denominator: int = BASE_TOKEN_DENOMINATOR, multiplier: float = 1.0
) -> float:
    """Probability of one or more finds over independent attempts."""
    if attempts < 0:
        raise ValueError("attempts cannot be negative")
    if attempts == 0:
        return 0.0
    p = per_chest_probability(denominator, multiplier)
    if p >= 1.0:
        return 1.0
    return -math.expm1(attempts * math.log1p(-p))


def mixed_chance(counts: dict[str, int], multipliers: dict[str, float]) -> float:
    """Cumulative chance when openings happened under different multipliers."""
    probability_of_no_find = 1.0
    for mode, attempts in counts.items():
        if attempts < 0:
            raise ValueError("attempt counts cannot be negative")
        if attempts == 0:
            continue
        multiplier = multipliers.get(mode, 1.0)
        p = per_chest_probability(BASE_TOKEN_DENOMINATOR, multiplier)
        if p >= 1.0:
            return 1.0
        probability_of_no_find *= math.exp(attempts * math.log1p(-p))
    return 1.0 - probability_of_no_find


def chests_for_chance(target: float, denominator: int = BASE_TOKEN_DENOMINATOR,
                       multiplier: float = 1.0) -> int:
    """Smallest integer number of independent openings reaching target probability."""
    if not 0.0 < target < 1.0:
        raise ValueError("target must be between 0 and 1")
    p = per_chest_probability(denominator, multiplier)
    if p >= 1.0:
        return 1
    return math.ceil(math.log1p(-target) / math.log1p(-p))
