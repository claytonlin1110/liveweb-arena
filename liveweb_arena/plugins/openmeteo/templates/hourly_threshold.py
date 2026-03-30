"""Hourly threshold counting template for Open Meteo - MEDIUM DIFFICULTY.

Asks how many hours today a given metric is above or below a threshold
in a given city. The agent starts on the generic docs page, finds the city,
then counts qualifying hours from the hourly forecast table.

Dynamic data: hourly forecasts update continuously.
Time-sensitive: asks about "today" which changes daily.
Computation required: agent must count hours, not read a single value.

SFT defense:
- Threshold includes a seed-derived offset (±2.0 for temp, scaled for others),
  so the exact threshold is never a memorizable constant.
- Strict scoring: exact count only for 1.0, off-by-1 for 0.5.
  On a 0-24 range, SFT with climate priors may guess close but rarely exact.

Effective variants: 170 cities x 4 metrics x ~8 base thresholds x continuous offset
                    x 2 directions → effectively continuous.
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

from .common import DOCS_HOME_URL, docs_url_from_coord_key, get_collected_location_data, get_today_hourly_series
from .variables import CITIES, HourlyMetric, HOURLY_THRESHOLDS

# Per-metric jitter half-range applied to each base threshold.
# Prevents SFT from memorising fixed threshold→count mappings.
_THRESHOLD_JITTER = {
    "temperature_2m": 2.0,       # ±2 °C
    "relative_humidity_2m": 5.0,  # ±5 %
    "wind_speed_10m": 3.0,       # ±3 km/h
    "precipitation_probability": 5.0,  # ±5 %
}


PATTERNS_ABOVE = {
    HourlyMetric.TEMPERATURE: [
        "According to Open-Meteo, how many hours today will the temperature in {city} be above {threshold}{unit}?",
        "Using Open-Meteo, count the hours today when {city}'s temperature exceeds {threshold}{unit}.",
        "On Open-Meteo, for how many hours today is {city}'s temperature forecast above {threshold}{unit}?",
    ],
    HourlyMetric.HUMIDITY: [
        "According to Open-Meteo, how many hours today will the relative humidity in {city} be above {threshold}{unit}?",
        "Using Open-Meteo, count the hours today when {city}'s humidity exceeds {threshold}{unit}.",
    ],
    HourlyMetric.WIND_SPEED: [
        "According to Open-Meteo, how many hours today will the wind speed in {city} be above {threshold} {unit}?",
        "Using Open-Meteo, count the hours today when {city}'s wind speed exceeds {threshold} {unit}.",
    ],
    HourlyMetric.PRECIP_PROBABILITY: [
        "According to Open-Meteo, how many hours today will the precipitation probability in {city} be above {threshold}{unit}?",
        "Using Open-Meteo, count the hours today when {city}'s precipitation probability exceeds {threshold}{unit}.",
    ],
}

PATTERNS_BELOW = {
    HourlyMetric.TEMPERATURE: [
        "According to Open-Meteo, how many hours today will the temperature in {city} be below {threshold}{unit}?",
        "Using Open-Meteo, count the hours today when {city}'s temperature is below {threshold}{unit}.",
        "On Open-Meteo, for how many hours today is {city}'s temperature forecast below {threshold}{unit}?",
    ],
    HourlyMetric.HUMIDITY: [
        "According to Open-Meteo, how many hours today will the relative humidity in {city} be below {threshold}{unit}?",
        "Using Open-Meteo, count the hours today when {city}'s humidity is below {threshold}{unit}.",
    ],
    HourlyMetric.WIND_SPEED: [
        "According to Open-Meteo, how many hours today will the wind speed in {city} be below {threshold} {unit}?",
        "Using Open-Meteo, count the hours today when {city}'s wind speed is below {threshold} {unit}.",
    ],
    HourlyMetric.PRECIP_PROBABILITY: [
        "According to Open-Meteo, how many hours today will the precipitation probability in {city} be below {threshold}{unit}?",
        "Using Open-Meteo, count the hours today when {city}'s precipitation probability is below {threshold}{unit}.",
    ],
}


@register_template("openmeteo_hourly_threshold")
class OpenMeteoHourlyThresholdTemplate(QuestionTemplate):
    """
    MEDIUM: Count hours above/below a jittered threshold for a metric today.

    Requires scanning hourly forecast data and counting qualifying entries.
    Threshold includes a seed-derived random offset so SFT cannot memorise
    fixed threshold-to-count mappings. Scoring is strict: exact = 1.0,
    off-by-1 = 0.5, off-by->1 = 0.0.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("openmeteo_hourly_threshold")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)

        metrics = list(HourlyMetric)
        metric = metrics[variant % len(metrics)] if variant is not None else rng.choice(metrics)

        base_thresholds = HOURLY_THRESHOLDS[metric.api_field]
        base = rng.choice(base_thresholds)
        jitter_range = _THRESHOLD_JITTER[metric.api_field]
        offset = rng.uniform(-jitter_range, jitter_range)
        # Round to 1 decimal so the question reads naturally
        threshold = round(base + offset, 1)

        is_above = rng.choice([True, False])

        city = rng.choice(CITIES)
        patterns = PATTERNS_ABOVE[metric] if is_above else PATTERNS_BELOW[metric]
        question_text = rng.choice(patterns).format(
            city=city.display_name,
            threshold=threshold,
            unit=metric.unit,
        )

        return GeneratedQuestion(
            question_text=question_text,
            start_url=DOCS_HOME_URL,
            variables={"city": city.name, "metric": metric.name, "threshold": threshold, "is_above": is_above},
            validation_info={
                "city_name": city.name,
                "coord_key": city.coord_key,
                "metric_field": metric.api_field,
                "metric_label": metric.display_name,
                "unit": metric.unit,
                "threshold": threshold,
                "is_above": is_above,
            },
            template_name=self.name,
            expected_steps=7,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        city = validation_info.get("city_name", "")
        label = validation_info.get("metric_label", "hourly temperature")
        unit = validation_info.get("unit", "°C")
        threshold = validation_info.get("threshold", 0)
        is_above = validation_info.get("is_above", True)
        direction = "above" if is_above else "below"
        return f"""Task-Specific Rules (Open Meteo Hourly Threshold Count):
- City: {city}
- Count hours today where {label} is strictly {direction} {threshold}{unit}
- Answer should be a whole number (0-24)
- Score 1.0: Exact count
- Score 0.5: Off by exactly 1 hour
- Score 0.0: Off by more than 1 hour or no numeric answer
- Use the hourly forecast for today's local date"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        coord_key = validation_info.get("coord_key", "")
        city_name = validation_info.get("city_name", "")
        metric_field = validation_info.get("metric_field", "temperature_2m")
        threshold = validation_info.get("threshold", 0)
        is_above = validation_info.get("is_above", True)

        data, failure = get_collected_location_data(coord_key, city_name)
        if failure is not None:
            return failure

        values, val_failure = get_today_hourly_series(data, metric_field)
        if val_failure is not None:
            return val_failure

        if is_above:
            count = sum(1 for v in values if v > threshold)
        else:
            count = sum(1 for v in values if v < threshold)

        return GroundTruthResult.ok(str(count))

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
