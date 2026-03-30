"""Hourly time-of-extremum template for Open Meteo - MEDIUM DIFFICULTY.

Asks at what time today a city will reach its peak or lowest hourly value
for a given metric. The agent starts on the generic docs page, finds the
city, then scans the hourly forecast to find the argmax/argmin time.

Dynamic data: hourly forecasts update continuously.
Time-sensitive: asks about "today" which changes daily.
Computation required: agent must find the extremum AND report its time.

SFT defense:
- Temperature is EXCLUDED because its diurnal cycle is a textbook fixed
  pattern (peak ~14:00, min ~05:00) that SFT can memorise.
- Remaining metrics (humidity, wind speed, precipitation probability) have
  weather-dependent patterns that vary significantly by day and location.
- Humidity has a weak inverse-temperature pattern (~40% reliable) but the
  exact hour varies enough that ±1h accuracy is hard without reading data.

Effective variants: 170 cities x 3 metrics x 2 (max/min) = 1,020 (>500).
"""

import random
from typing import Any, Dict, List, Optional

from liveweb_arena.core.validators.base import (
    QuestionTemplate, GeneratedQuestion, ValidationResult, register_template,
)
from liveweb_arena.core.ground_truth_trigger import (
    UrlPatternTrigger, TriggerConfig, GroundTruthResult,
)
from liveweb_arena.core.gt_collector import GTSourceType

from .common import DOCS_HOME_URL, docs_url_from_coord_key, get_collected_location_data, get_today_hourly_pairs
from .variables import CITIES, HourlyMetric

# Exclude TEMPERATURE — its diurnal cycle (peak ~14:00, min ~05:00) is a
# fixed pattern that SFT can exploit for easy partial credit.
TIME_OF_METRICS: List[HourlyMetric] = [
    HourlyMetric.HUMIDITY,
    HourlyMetric.WIND_SPEED,
    HourlyMetric.PRECIP_PROBABILITY,
]

PATTERNS_MAX = {
    HourlyMetric.HUMIDITY: [
        "At what time today will {city} reach its peak hourly relative humidity according to Open-Meteo?",
        "Using Open-Meteo, find the hour today when {city}'s humidity is highest.",
        "On Open-Meteo, what time today does {city} hit its maximum hourly humidity?",
    ],
    HourlyMetric.WIND_SPEED: [
        "At what time today will {city} reach its peak hourly wind speed according to Open-Meteo?",
        "Using Open-Meteo, find the hour today when {city}'s wind speed is highest.",
        "On Open-Meteo, what time today does {city} hit its maximum hourly wind speed?",
    ],
    HourlyMetric.PRECIP_PROBABILITY: [
        "At what time today will {city} reach its peak hourly precipitation probability according to Open-Meteo?",
        "Using Open-Meteo, find the hour today when {city}'s precipitation probability is highest.",
        "On Open-Meteo, what time today does {city} hit its maximum precipitation probability?",
    ],
}

PATTERNS_MIN = {
    HourlyMetric.HUMIDITY: [
        "At what time today will {city} reach its lowest hourly relative humidity according to Open-Meteo?",
        "Using Open-Meteo, find the hour today when {city}'s humidity is lowest.",
        "On Open-Meteo, what time today does {city} hit its minimum hourly humidity?",
    ],
    HourlyMetric.WIND_SPEED: [
        "At what time today will {city} reach its lowest hourly wind speed according to Open-Meteo?",
        "Using Open-Meteo, find the hour today when {city}'s wind speed is lowest.",
        "On Open-Meteo, what time today does {city} hit its minimum hourly wind speed?",
    ],
    HourlyMetric.PRECIP_PROBABILITY: [
        "At what time today will {city} reach its lowest hourly precipitation probability according to Open-Meteo?",
        "Using Open-Meteo, find the hour today when {city}'s precipitation probability is lowest.",
        "On Open-Meteo, what time today does {city} hit its minimum hourly precipitation probability?",
    ],
}


@register_template("openmeteo_hourly_time_of")
class OpenMeteoHourlyTimeOfTemplate(QuestionTemplate):
    """
    MEDIUM: Find the time of the hourly peak or low for a metric today.

    Requires scanning hourly forecast data to find argmax/argmin.
    Tie-breaking: first (earliest) hour wins.
    Temperature excluded (fixed diurnal pattern exploitable by SFT).
    170 cities x 3 metrics x 2 (max/min) = 1,020 effective variants.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("openmeteo_hourly_time_of")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)

        metric = (
            TIME_OF_METRICS[variant % len(TIME_OF_METRICS)]
            if variant is not None
            else rng.choice(TIME_OF_METRICS)
        )
        is_max = rng.choice([True, False])

        city = rng.choice(CITIES)
        patterns = PATTERNS_MAX[metric] if is_max else PATTERNS_MIN[metric]
        question_text = rng.choice(patterns).format(city=city.display_name)

        return GeneratedQuestion(
            question_text=question_text,
            start_url=DOCS_HOME_URL,
            variables={"city": city.name, "is_max": is_max, "metric": metric.name},
            validation_info={
                "city_name": city.name,
                "coord_key": city.coord_key,
                "is_max": is_max,
                "metric_field": metric.api_field,
                "metric_label": metric.display_name,
                "unit": metric.unit,
            },
            template_name=self.name,
            expected_steps=7,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        city = validation_info.get("city_name", "")
        is_max = validation_info.get("is_max", True)
        label = validation_info.get("metric_label", "hourly wind speed")
        extrema = "peak (highest)" if is_max else "lowest (minimum)"
        return f"""Task-Specific Rules (Open Meteo Hourly Time Of Extremum):
- City: {city}
- Looking for: time of {extrema} {label} today
- Answer should be a time (e.g. "14:00", "2 PM", "14h")
- Score 1.0: Exact hour match
- Score 0.5: Within ±1 hour
- Score 0.0: Off by more than 1 hour or no answer
- If multiple hours tie, the earliest hour is correct
- Use the hourly forecast for today's local date"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        coord_key = validation_info.get("coord_key", "")
        is_max = validation_info.get("is_max", True)
        city_name = validation_info.get("city_name", "")
        metric_field = validation_info.get("metric_field", "wind_speed_10m")

        data, failure = get_collected_location_data(coord_key, city_name)
        if failure is not None:
            return failure

        pairs, pair_failure = get_today_hourly_pairs(data, metric_field)
        if pair_failure is not None:
            return pair_failure

        # Degenerate case: all values identical (e.g., precip=0 for arid cities).
        # argmax/argmin would always return 00:00, which SFT can memorize.
        values = [v for _, v in pairs]
        if len(set(values)) == 1:
            return GroundTruthResult.fail(
                f"All {len(values)} hourly {metric_field} values are identical "
                f"({values[0]}) — degenerate case, no meaningful extremum"
            )

        # Find argmax/argmin — first occurrence wins ties
        if is_max:
            best_time, best_val = pairs[0]
            for time_str, val in pairs[1:]:
                if val > best_val:
                    best_val = val
                    best_time = time_str
        else:
            best_time, best_val = pairs[0]
            for time_str, val in pairs[1:]:
                if val < best_val:
                    best_val = val
                    best_time = time_str

        # Extract time portion: "2026-03-20T14:00" -> "14:00"
        if "T" in best_time:
            time_part = best_time.split("T", 1)[1]
        else:
            time_part = best_time

        return GroundTruthResult.ok(time_part)

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
