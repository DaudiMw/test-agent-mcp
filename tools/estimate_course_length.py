from typing import Literal
from tavily import TavilyClient

from mcp_instance import mcp, TAVILY_API_KEY

_client = TavilyClient(api_key=TAVILY_API_KEY)

# Multipliers applied to the baseline estimate based on skill level.
# A beginner takes ~40% longer; an advanced learner ~25% less.
_SKILL_MULTIPLIER = {
    "beginner": 1.4,
    "intermediate": 1.0,
    "advanced": 0.75,
}


@mcp.tool()
def estimate_course_length(
    course_name: str,
    skill_level: Literal["beginner", "intermediate", "advanced"] = "intermediate",
) -> dict:
    """Estimate how many hours it takes to complete a course or earn a certification.

    Searches the web for duration information about the course, then adjusts the
    estimate based on the learner's skill level. Returns a range and a recommended
    value ready to pass directly into create_learning_plan as est_course_hours.

    Args:
        course_name: Name of the course or certification to look up
            (e.g. "AWS Solutions Architect Associate", "Google Data Analytics Certificate").
        skill_level: The learner's current experience level with this topic.
            "beginner"     — little to no prior knowledge (~40% more time needed)
            "intermediate" — some relevant background (baseline estimate)
            "advanced"     — strong existing knowledge (~25% less time needed)
    """
    try:
        query = f'how many hours to complete "{course_name}" course certification'
        response = _client.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )

        # Tavily returns a synthesised answer and individual result snippets.
        # We use both to extract a numeric hour estimate.
        answer = response.get("answer", "")
        snippets = " ".join(
            r.get("content", "") for r in response.get("results", [])
        )
        combined = f"{answer} {snippets}"

        baseline = _extract_hours(combined)

        if baseline is None:
            return {
                "error": (
                    f"Could not find reliable duration information for '{course_name}'. "
                    "Please provide est_course_hours manually."
                )
            }

        multiplier = _SKILL_MULTIPLIER[skill_level]
        recommended = round(baseline * multiplier, 1)
        min_hours = round(recommended * 0.8, 1)
        max_hours = round(recommended * 1.2, 1)

        return {
            "course_name": course_name,
            "skill_level": skill_level,
            "recommended_hours": recommended,
            "min_hours": min_hours,
            "max_hours": max_hours,
            "sources": [r.get("url") for r in response.get("results", [])[:3]],
            "note": (
                f"Baseline estimate: {baseline}h. "
                f"Adjusted for {skill_level} level (×{multiplier})."
            ),
        }

    except Exception as e:
        return {"error": str(e)}


def _extract_hours(text: str) -> float | None:
    """Parse the first plausible hour figure out of a block of text.

    Looks for patterns like '40 hours', '20-30 hours', 'approximately 15 hours'.
    Returns the midpoint when a range is found, otherwise the single value.
    Returns None if nothing usable is found.
    """
    import re

    # Match patterns like "20-30 hours", "20 to 30 hours", "20 hours"
    range_pattern = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:–|-|to)\s*(\d+(?:\.\d+)?)\s*hours?',
        re.IGNORECASE,
    )
    single_pattern = re.compile(
        r'(\d+(?:\.\d+)?)\s*hours?',
        re.IGNORECASE,
    )

    range_match = range_pattern.search(text)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        # Sanity check: ignore implausible values (< 1h or > 2000h)
        if 1 <= low <= 2000 and 1 <= high <= 2000:
            return round((low + high) / 2, 1)

    single_match = single_pattern.search(text)
    if single_match:
        hours = float(single_match.group(1))
        if 1 <= hours <= 2000:
            return hours

    return None
