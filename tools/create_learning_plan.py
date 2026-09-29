from typing import Tuple, Optional
from datetime import time, datetime, timedelta, date
import base64
import uuid
from pydantic import BaseModel, Field, model_validator
from icalendar import Calendar, Event

from app import mcp

_DAY_FIELD_DESC = (
    "Availability window as [start, end] in 'HH:MM:SS' format (e.g. ['09:00:00', '17:00:00']). "
    "Omit or set to null if unavailable this day."
)


class Schedule(BaseModel):
    monday: Optional[Tuple[time, time]] = Field(default=None, description=_DAY_FIELD_DESC)
    tuesday: Optional[Tuple[time, time]] = Field(default=None, description=_DAY_FIELD_DESC)
    wednesday: Optional[Tuple[time, time]] = Field(default=None, description=_DAY_FIELD_DESC)
    thursday: Optional[Tuple[time, time]] = Field(default=None, description=_DAY_FIELD_DESC)
    friday: Optional[Tuple[time, time]] = Field(default=None, description=_DAY_FIELD_DESC)
    saturday: Optional[Tuple[time, time]] = Field(default=None, description=_DAY_FIELD_DESC)
    sunday: Optional[Tuple[time, time]] = Field(default=None, description=_DAY_FIELD_DESC)

    @model_validator(mode='after')
    def check_end_after_start(self):
        errors = []

        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if value is not None and value[0] >= value[1]:
                errors.append(name)

        if errors:
            raise ValueError(
                f"Start time must be before end time. Affected days: {errors}"
            )

        return self


# Maps Python weekday() integer (Mon=0 … Sun=6) to Schedule field name
_WEEKDAY_FIELD = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


@mcp.tool()
def create_learning_plan(
    user_schedule: Schedule,
    date_to_achieve: datetime,
    est_course_hours: float,
    course_name: str = "Learning Plan",
) -> dict:
    """
    Generate an ICS calendar file that schedules study sessions for a course.

    The tool distributes the total estimated course hours across the user's
    available weekly time slots, starting from today until the target date.
    Each study session is created as a timed calendar event using the schedule
    windows provided.

    The ICS file content is returned as a base64-encoded string so that it can
    be transmitted over HTTP and decoded by the caller into a downloadable file.

    :param user_schedule: Weekly availability. Each day is an optional
        (start_time, end_time) tuple. Omit days when the user is unavailable.
    :param date_to_achieve: The deadline by which the course should be finished.
    :param est_course_hours: Total number of hours the course requires.
    :param course_name: Display name used as the event title in the calendar.
    :returns: A dict with keys:
        - ``filename``: suggested filename for the download (e.g. "learning_plan.ics")
        - ``content_type``: MIME type ("text/calendar")
        - ``data_base64``: base64-encoded ICS file content
        - ``sessions_scheduled``: number of calendar events created
        - ``hours_scheduled``: total hours successfully scheduled
    """
    today = date.today()
    deadline = date_to_achieve.date() if isinstance(date_to_achieve, datetime) else date_to_achieve

    # --- Pre-flight validation ---
    if deadline <= today:
        raise ValueError(
            f"date_to_achieve ({deadline}) must be in the future. Today is {today}."
        )

    # Calculate total available hours between today and the deadline
    available_hours = 0.0
    scan_day = today
    while scan_day <= deadline:
        slot = getattr(user_schedule, _WEEKDAY_FIELD[scan_day.weekday()])
        if slot is not None:
            slot_hours = (
                datetime.combine(scan_day, slot[1]) - datetime.combine(scan_day, slot[0])
            ).total_seconds() / 3600
            available_hours += slot_hours
        scan_day += timedelta(days=1)

    if available_hours == 0:
        raise ValueError(
            "No available study slots found between today and the deadline. "
            "Please set at least one day in user_schedule."
        )

    if available_hours < est_course_hours:
        raise ValueError(
            f"Not enough time to complete the course. "
            f"The schedule provides {available_hours:.1f}h before {deadline}, "
            f"but the course requires {est_course_hours:.1f}h. "
            f"Consider extending the deadline or adding more study days."
        )
    # --- End pre-flight ---

    remaining_hours = est_course_hours
    sessions = 0
    hours_scheduled = 0.0

    cal = Calendar()
    cal.add("prodid", "-//Learning Plan MCP//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", course_name)

    current_day = today
    while current_day <= deadline and remaining_hours > 0:
        field_name = _WEEKDAY_FIELD[current_day.weekday()]
        slot = getattr(user_schedule, field_name)

        if slot is not None:
            start_time, end_time = slot

            slot_start_dt = datetime.combine(current_day, start_time)
            slot_end_dt = datetime.combine(current_day, end_time)
            slot_hours = (slot_end_dt - slot_start_dt).total_seconds() / 3600

            # Cap the final session at the remaining hours needed
            session_hours = min(slot_hours, remaining_hours)
            if remaining_hours < slot_hours:
                slot_end_dt = slot_start_dt + timedelta(hours=remaining_hours)

            event = Event()
            event.add("summary", course_name)
            event.add("dtstart", slot_start_dt)
            event.add("dtend", slot_end_dt)
            event.add("uid", str(uuid.uuid4()))
            event.add(
                "description",
                f"Study session for '{course_name}'. "
                f"{session_hours:.1f}h of {est_course_hours:.1f}h total.",
            )
            cal.add_component(event)

            remaining_hours -= session_hours
            hours_scheduled += session_hours
            sessions += 1

        current_day += timedelta(days=1)

    ics_bytes = cal.to_ical()
    safe_name = course_name.lower().replace(" ", "_")

    return {
        "filename": f"{safe_name}.ics",
        "content_type": "text/calendar",
        "data_base64": base64.b64encode(ics_bytes).decode("ascii"),
        "sessions_scheduled": sessions,
        "hours_scheduled": round(hours_scheduled, 2),
    }
