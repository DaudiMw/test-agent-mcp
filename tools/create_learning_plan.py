from typing import Tuple, Optional, Dict, Any
from datetime import time, datetime, timedelta, date
import os
import uuid
import boto3
from pydantic import BaseModel, Field, model_validator
from icalendar import Calendar, Event

from mcp_instance import mcp, S3_BUCKET

# On ECS, Task Role credentials are injected automatically.
# Region must be explicit so presigned URLs are signed for the correct endpoint.
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
_s3 = boto3.client("s3", region_name=_AWS_REGION)

_PRESIGNED_URL_TTL = 3600  # seconds — 1 hour

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
) -> dict:
    """Generate an ICS calendar file that schedules study sessions for a course.

    The tool distributes total estimated course hours across available weekly time slots
    until the target date. Uploads the ICS file to S3 and returns a presigned download
    URL that expires after 1 hour.

    Args:
        user_schedule: Dict with weekday names as keys ('monday'..'sunday') and
            [start_time, end_time] string tuples in 'HH:MM:SS' format as values.
        date_to_achieve: Deadline in YYYY-MM-DD format (e.g., '2026-10-15').
        est_course_hours: Total hours required to finish the course.
        course_name: Display name for the calendar event.
    """
    # Parse schedule dictionary into Pydantic model inside function body
    parsed_schedule = Schedule.model_validate(user_schedule)

    # Parse date_to_achieve string into a date object
    if isinstance(date_to_achieve, str):
        deadline = datetime.strptime(date_to_achieve, "%Y-%m-%d").date()
    else:
        deadline = date_to_achieve.date() if isinstance(date_to_achieve, datetime) else date_to_achieve

    today = date.today()

    # --- Pre-flight validation ---
    if deadline <= today:
        raise ValueError(
            f"date_to_achieve ({deadline}) must be in the future. Today is {today}."
        )

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
        raise ValueError(
            "No available study slots found between today and the deadline."
        )

    if available_hours < est_course_hours:
        raise ValueError(
            f"Not enough time to complete the course. "
            f"Schedule provides {available_hours:.1f}h before {deadline}, "
            f"but the course requires {est_course_hours:.1f}h."
        )

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
    s3_key = f"learning-plans/{uuid.uuid4()}/{filename}"

    _s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=ics_bytes,
        ContentType="text/calendar",
        ContentDisposition=f'attachment; filename="{filename}"',
    )

    download_url = _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": s3_key},
        ExpiresIn=_PRESIGNED_URL_TTL,
    )

    return {
        "download_url": download_url,
        "filename": filename,
        "sessions_scheduled": sessions,
        "hours_scheduled": round(hours_scheduled, 2),
        "expires_in_seconds": _PRESIGNED_URL_TTL,
    }