from typing import Tuple, Optional, Dict, Any, Union
from datetime import time, datetime, timedelta, date
import uuid
from pydantic import BaseModel, Field, model_validator
from icalendar import Calendar, Event
from fastmcp.utilities.types import File

from mcp_instance import mcp

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


_WEEKDAY_FIELD = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


@mcp.tool()
def create_learning_plan(
    user_schedule: Dict[str, Any],
    date_to_achieve: str,
    est_course_hours: float,
    course_name: str = "Learning Plan",
) -> Union[File, dict]:
    """Generate an ICS calendar file that schedules study sessions for a course.

    The tool distributes total estimated course hours across available weekly time
    slots until the target date. Returns the .ics file directly in the response so
    the caller can save or import it immediately — no download link required.

    Args:
        user_schedule: Dict with weekday names as keys ('monday'..'sunday') and
            [start_time, end_time] string tuples in 'HH:MM:SS' format as values.
        date_to_achieve: Deadline in YYYY-MM-DD format (e.g., '2027-06-01').
        est_course_hours: Total hours required to finish the course.
        course_name: Display name for the calendar event.
    """
    try:
        parsed_schedule = Schedule.model_validate(user_schedule)

        if isinstance(date_to_achieve, str):
            deadline = datetime.strptime(date_to_achieve, "%Y-%m-%d").date()
        else:
            deadline = date_to_achieve.date() if isinstance(date_to_achieve, datetime) else date_to_achieve

        today = date.today()

        # --- Pre-flight validation ---
        if deadline <= today:
            return {
                "error": f"date_to_achieve ({deadline}) must be in the future. Today is {today}."
            }

        available_hours = 0.0
        scan_day = today
        while scan_day <= deadline:
            slot = getattr(parsed_schedule, _WEEKDAY_FIELD[scan_day.weekday()])
            if slot is not None:
                slot_hours = (
                    datetime.combine(scan_day, slot[1]) - datetime.combine(scan_day, slot[0])
                ).total_seconds() / 3600
                available_hours += slot_hours
            scan_day += timedelta(days=1)

        if available_hours == 0:
            return {
                "error": "No available study slots found between today and the deadline. "
                         "Please set at least one day in user_schedule."
            }

        if available_hours < est_course_hours:
            return {
                "error": (
                    f"Not enough time to complete the course. "
                    f"Schedule provides {available_hours:.1f}h before {deadline}, "
                    f"but the course requires {est_course_hours:.1f}h. "
                    f"Consider extending the deadline or adding more study days."
                )
            }

        # --- Generate Calendar ---
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
            slot = getattr(parsed_schedule, field_name)

            if slot is not None:
                start_time, end_time = slot

                slot_start_dt = datetime.combine(current_day, start_time)
                slot_end_dt = datetime.combine(current_day, end_time)
                slot_hours = (slot_end_dt - slot_start_dt).total_seconds() / 3600

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
        filename = f"{safe_name}.ics"

        # Return the file inline — the MCP client receives it as an embedded resource
        # with mime_type text/calendar, ready to save or import directly.
        f = File(data=ics_bytes, name=filename, format="calendar")
        f._mime_type = "text/calendar"
        return f

    except Exception as e:
        return {"error": str(e)}
