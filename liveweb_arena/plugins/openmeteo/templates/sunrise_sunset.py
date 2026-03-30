"""Daylight duration template for Open Meteo - MEDIUM DIFFICULTY.

Asks how long the daylight period is in a city on a given day.
The agent starts on the generic docs page, finds the city, then reads
BOTH sunrise AND sunset from the daily forecast table and computes the
duration (sunset - sunrise).

Dynamic data: sunrise/sunset shift by ~1-4 minutes daily.
Computation required: read two time values and compute the difference.
Multi-value: requires both sunrise AND sunset — not a single-value read.

SFT defense:
- Answer is in "Xh Ym" format with minute-level precision.
- Scoring is tight: ±3 min for 1.0, ±10 min for 0.5.
- An LLM can estimate daylight ≈ f(latitude, date) to ±15-30 min, but
  rarely within ±3 min. The API uses its own atmospheric refraction model,
  so exact minute differs from astronomical tables.
- Near equinoxes (~12h), SFT's "12h 0m" guess is off by 5-20 min for
  most cities (exact duration depends on latitude + refraction).

Effective variants: 170 cities x 3 days x 3 patterns = 1,530 (>500).
"""

import random
from typing import Any, Dict, Optional

from liveweb_arena.core.validators.base import (
    QuestionTemplate, GeneratedQuestion, ValidationResult, register_template,
)
from liveweb_arena.core.ground_truth_trigger import (
    UrlPatternTrigger, TriggerConfig, GroundTruthResult,
)
from liveweb_arena.core.gt_collector import GTSourceType

from .common import DOCS_HOME_URL, docs_url_from_coord_key, get_collected_location_data
from .variables import CITIES


DAY_OPTIONS = [
    (0, "today"),
    (1, "tomorrow"),
    (2, "the day after tomorrow"),
]

PATTERNS = [
    "According to Open-Meteo, how long is the daylight period in {city} {day_label}? Answer in hours and minutes.",
    "Using Open-Meteo, what is the duration from sunrise to sunset in {city} {day_label}?",
    "On Open-Meteo, how many hours and minutes of daylight does {city} get {day_label}?",
]


@register_template("openmeteo_sunrise_sunset")
class OpenMeteoSunriseSunsetTemplate(QuestionTemplate):
    """
    MEDIUM: Compute daylight duration from sunrise and sunset times.

    Requires reading TWO values (sunrise + sunset) from the daily forecast
    table and computing the time difference. This is multi-step computation,
    not a single-value read — satisfying §4 gate 1 (non-trivial) and
    gate 3 (computation required).

    Tight scoring (±3 min for 1.0) prevents SFT from exploiting the
    latitude→daylight approximation.

    170 cities x 3 days x 3 patterns = 1,530 effective variants.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("openmeteo_sunrise_sunset")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)

        city = rng.choice(CITIES)
        day_idx, day_label = rng.choice(DAY_OPTIONS)
        pattern = rng.choice(PATTERNS)

        question_text = pattern.format(
            city=city.display_name,
            day_label=day_label,
        )

        return GeneratedQuestion(
            question_text=question_text,
            start_url=DOCS_HOME_URL,
            variables={"city": city.name, "day_idx": day_idx},
            validation_info={
                "city_name": city.name,
                "coord_key": city.coord_key,
                "day_idx": day_idx,
                "day_label": day_label,
            },
            template_name=self.name,
            expected_steps=7,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        city = validation_info.get("city_name", "")
        day_label = validation_info.get("day_label", "today")
        return f"""Task-Specific Rules (Open Meteo Daylight Duration):
- City: {city}
- Day: {day_label}
- Read both sunrise and sunset times, compute the difference
- Answer should be in hours and minutes (e.g. "12h 18m", "12 hours 18 minutes")
- Score 1.0: Within ±3 minutes of correct duration
- Score 0.5: Within ±10 minutes
- Score 0.0: Off by more than 10 minutes or no answer
- Use the daily forecast table on Open-Meteo"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        coord_key = validation_info.get("coord_key", "")
        city_name = validation_info.get("city_name", "")
        day_idx = validation_info.get("day_idx", 0)

        data, failure = get_collected_location_data(coord_key, city_name)
        if failure is not None:
            return failure

        daily = data.get("daily")
        if not daily:
            return GroundTruthResult.fail("No daily data in API response")

        sunrise_list = daily.get("sunrise")
        sunset_list = daily.get("sunset")
        if not sunrise_list or not sunset_list:
            return GroundTruthResult.fail("No sunrise/sunset data in daily forecast")

        if len(sunrise_list) <= day_idx or len(sunset_list) <= day_idx:
            return GroundTruthResult.fail(
                f"Need at least {day_idx + 1} days of sunrise/sunset data"
            )

        sunrise_str = sunrise_list[day_idx]
        sunset_str = sunset_list[day_idx]

        # Polar regions may have null sunrise/sunset
        if not sunrise_str or not sunset_str:
            return GroundTruthResult.fail(
                f"Sunrise or sunset is null for {city_name} on day {day_idx} "
                "(possible polar day/night)"
            )

        # Parse ISO timestamps: "2026-03-20T06:15" format
        try:
            sr_parts = str(sunrise_str).split("T", 1)
            ss_parts = str(sunset_str).split("T", 1)
            sr_time = sr_parts[1] if len(sr_parts) == 2 else sr_parts[0]
            ss_time = ss_parts[1] if len(ss_parts) == 2 else ss_parts[0]

            sr_h, sr_m = int(sr_time.split(":")[0]), int(sr_time.split(":")[1])
            ss_h, ss_m = int(ss_time.split(":")[0]), int(ss_time.split(":")[1])
        except (ValueError, IndexError) as e:
            return GroundTruthResult.fail(
                f"Failed to parse sunrise/sunset times: {sunrise_str}, {sunset_str}: {e}"
            )

        total_sr = sr_h * 60 + sr_m
        total_ss = ss_h * 60 + ss_m
        duration_min = total_ss - total_sr

        if duration_min < 0:
            return GroundTruthResult.fail(
                f"Sunset before sunrise: {sunrise_str} / {sunset_str}"
            )

        hours = duration_min // 60
        minutes = duration_min % 60
        return GroundTruthResult.ok(f"{hours}h {minutes}m")

    async def validate_answer(
        self, answer: str, validation_info: Dict[str, Any]
    ) -> ValidationResult:
        """Not used — the pipeline uses LLM-based validation via get_validation_rules()."""
        return ValidationResult(
            score=0.0, is_correct=False, expected=None, actual=answer,
            details="Use LLM validation",
        )

    def get_ground_truth_trigger(self, validation_info: dict) -> TriggerConfig:
        trigger = UrlPatternTrigger(domains=["open-meteo.com"])
        return TriggerConfig(trigger=trigger)

    @classmethod
    def get_cache_source(cls) -> str:
        return "openmeteo"

    def get_gt_source(self) -> GTSourceType:
        return self.GT_SOURCE

    def get_probe_urls(self, validation_info: Dict[str, Any]) -> list[str]:
        coord_key = validation_info.get("coord_key", "")
        if isinstance(coord_key, str) and "," in coord_key:
            return [docs_url_from_coord_key(coord_key)]
        return []
