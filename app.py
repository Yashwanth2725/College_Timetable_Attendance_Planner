import math
from datetime import datetime
from types import SimpleNamespace

from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

from config import Config


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(
    __name__,
    template_folder="app/templates",
    static_folder="app/static"
)

app.config.from_object(Config)

db = SQLAlchemy(app)


# ============================================================
# DATABASE MODELS
# ============================================================

class Semester(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(100),
        nullable=False,
        unique=True
    )

    is_active = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )


class Subject(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )

    subject_type = db.Column(
        db.String(20),
        nullable=False
    )

    semester_id = db.Column(
        db.Integer,
        db.ForeignKey("semester.id"),
        nullable=False
    )

    semester = db.relationship(
        "Semester",
        backref="subjects"
    )


class Timetable(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    subject_id = db.Column(
        db.Integer,
        db.ForeignKey("subject.id"),
        nullable=False
    )

    day = db.Column(
        db.String(20),
        nullable=False
    )

    start_time = db.Column(
        db.String(10),
        nullable=False
    )

    end_time = db.Column(
        db.String(10),
        nullable=False
    )

    subject = db.relationship(
        "Subject",
        backref="timetable_entries"
    )


class Attendance(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    subject_id = db.Column(
        db.Integer,
        db.ForeignKey("subject.id"),
        nullable=False
    )

    date = db.Column(
        db.String(10),
        nullable=False
    )

    status = db.Column(
        db.String(20),
        nullable=False
    )

    subject = db.relationship(
        "Subject",
        backref="attendance_records"
    )


class TimetableChange(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    timetable_id = db.Column(
        db.Integer,
        db.ForeignKey("timetable.id"),
        nullable=False
    )

    # Date on which the original timetable class is affected.
    change_date = db.Column(
        db.String(10),
        nullable=True
    )

    change_type = db.Column(
        db.String(20),
        nullable=False
    )

    new_day = db.Column(
        db.String(20),
        nullable=True
    )

    new_start_time = db.Column(
        db.String(10),
        nullable=True
    )

    new_end_time = db.Column(
        db.String(10),
        nullable=True
    )

    reason = db.Column(
        db.String(255),
        nullable=True
    )

    timetable = db.relationship(
        "Timetable",
        backref="changes"
    )


# ============================================================
# DAY ORDER
# ============================================================

DAY_ORDER = {
    "Monday": 1,
    "Tuesday": 2,
    "Wednesday": 3,
    "Thursday": 4,
    "Friday": 5,
    "Saturday": 6
}


# ============================================================
# DATABASE COMPATIBILITY
# ============================================================

def ensure_database_columns():

    """
    Adds the new change_date column to an existing
    TimetableChange table if it does not already exist.

    This allows the updated application to work with
    an existing SQLite or PostgreSQL database.
    """

    inspector = db.inspect(db.engine)

    if "timetable_change" not in inspector.get_table_names():
        return

    columns = [
        column["name"]
        for column in inspector.get_columns(
            "timetable_change"
        )
    ]

    if "change_date" in columns:
        return

    dialect = db.engine.dialect.name

    with db.engine.begin() as connection:

        if dialect == "sqlite":

            connection.exec_driver_sql(
                """
                ALTER TABLE timetable_change
                ADD COLUMN change_date VARCHAR(10)
                """
            )

        elif dialect == "postgresql":

            connection.exec_driver_sql(
                """
                ALTER TABLE timetable_change
                ADD COLUMN change_date VARCHAR(10)
                """
            )


# ============================================================
# GET ACTIVE SEMESTER
# ============================================================

def get_active_semester():

    semester = Semester.query.filter_by(
        is_active=True
    ).first()

    if semester:
        return semester

    semester = Semester.query.order_by(
        Semester.id
    ).first()

    if semester:

        semester.is_active = True

        db.session.commit()

        return semester

    semester = Semester(
        name="Semester 1",
        is_active=True
    )

    db.session.add(semester)

    db.session.commit()

    return semester


# ============================================================
# EFFECTIVE TIMETABLE
# ============================================================

def get_effective_classes(
    selected_date
):

    """
    Returns the classes that actually apply to a
    particular calendar date.

    This is intentionally date-based rather than
    weekday-only.

    Example:

    Saturday 2026-08-22:
        Class cancelled -> it will not appear.

    Saturday 2026-08-29:
        Normal timetable -> class appears normally.
    """

    active_semester = get_active_semester()

    # Accept either a datetime.date object or a
    # YYYY-MM-DD string.
    if hasattr(
        selected_date,
        "strftime"
    ):

        target_date = selected_date.strftime(
            "%Y-%m-%d"
        )

        target_day = selected_date.strftime(
            "%A"
        )

    else:

        target_date = str(
            selected_date
        )

        try:

            target_day = datetime.strptime(
                target_date,
                "%Y-%m-%d"
            ).strftime("%A")

        except ValueError:

            return []

    entries = (
        Timetable.query
        .join(Subject)
        .filter(
            Subject.semester_id == active_semester.id
        )
        .all()
    )

    effective_classes = []

    for entry in entries:

        # ----------------------------------------------------
        # CHANGES FOR THIS EXACT DATE
        # ----------------------------------------------------

        date_changes = (
            TimetableChange.query
            .filter_by(
                timetable_id=entry.id,
                change_date=target_date
            )
            .order_by(
                TimetableChange.id.desc()
            )
            .all()
        )

        # ----------------------------------------------------
        # NEW DATE-AWARE SYSTEM
        # ----------------------------------------------------

        if date_changes:

            latest_change = date_changes[0]

            # Cancelled / postponed on this date
            if latest_change.change_type in [
                "Cancelled",
                "Postponed"
            ]:

                continue

            # Rescheduled / shifted on this date
            if latest_change.change_type in [
                "Rescheduled",
                "Shifted"
            ]:

                # If the new day is provided, the class
                # is displayed on that day for this
                # date-based entry.
                if latest_change.new_day == target_day:

                    effective_classes.append({
                        "timetable": entry,
                        "day": latest_change.new_day,
                        "start_time":
                            latest_change.new_start_time,
                        "end_time":
                            latest_change.new_end_time,
                        "changed": True,
                        "change_type":
                            latest_change.change_type
                    })

                continue

        # ----------------------------------------------------
        # OLD CHANGE RECORDS
        #
        # Existing changes created before this update may
        # have no change_date.
        #
        # We only treat them as active when they are
        # explicitly dated. This prevents an old cancellation
        # from incorrectly cancelling every future Saturday.
        # ----------------------------------------------------

        if target_day == entry.day:

            effective_classes.append({
                "timetable": entry,
                "day": entry.day,
                "start_time": entry.start_time,
                "end_time": entry.end_time,
                "changed": False,
                "change_type": None
            })

    effective_classes.sort(
        key=lambda item: item["start_time"]
    )

    return effective_classes


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    current_date = datetime.now()

    today_name = current_date.strftime(
        "%A"
    )

    today_date = current_date.strftime(
        "%Y-%m-%d"
    )

    active_semester = get_active_semester()

    today_classes = get_effective_classes(
        today_date
    )

    records = (
        Attendance.query
        .join(Subject)
        .filter(
            Subject.semester_id == active_semester.id
        )
        .all()
    )

    total_classes = len(records)

    total_present = sum(
        1
        for record in records
        if record.status == "Present"
    )

    if total_classes > 0:

        overall_percentage = (
            total_present / total_classes
        ) * 100

    else:

        overall_percentage = 0

    subjects = (
        Subject.query
        .filter_by(
            semester_id=active_semester.id
        )
        .order_by(
            Subject.name,
            Subject.subject_type
        )
        .all()
    )

    below_75 = []

    safe_subjects = []

    for subject in subjects:

        subject_records = Attendance.query.filter_by(
            subject_id=subject.id
        ).all()

        total = len(subject_records)

        present = sum(
            1
            for record in subject_records
            if record.status == "Present"
        )

        if total == 0:
            continue

        absent = total - present

        percentage = (
            present / total
        ) * 100

        if percentage >= 75:

            classes_can_miss = math.floor(
                (present / 0.75) - total
            )

            if classes_can_miss < 0:
                classes_can_miss = 0

            info = {
                "subject": subject,
                "total": total,
                "present": present,
                "absent": absent,
                "percentage": round(
                    percentage,
                    2
                ),
                "status": "SAFE",
                "classes_to_attend": 0,
                "classes_can_miss":
                    classes_can_miss
            }

            safe_subjects.append(info)

        else:

            required_classes = (
                (0.75 * total - present)
                / 0.25
            )

            classes_to_attend = math.ceil(
                required_classes
            )

            info = {
                "subject": subject,
                "total": total,
                "present": present,
                "absent": absent,
                "percentage": round(
                    percentage,
                    2
                ),
                "status": "BELOW 75%",
                "classes_to_attend":
                    classes_to_attend,
                "classes_can_miss": 0
            }

            below_75.append(info)

    return render_template(
        "home.html",
        today_name=today_name,
        today_date=today_date,
        today_classes=today_classes,
        total_classes=total_classes,
        total_present=total_present,
        overall_percentage=round(
            overall_percentage,
            2
        ),
        below_75=below_75,
        safe_subjects=safe_subjects,
        active_semester=active_semester
    )


# ============================================================
# SEMESTERS
# ============================================================

@app.route(
    "/semesters",
    methods=["GET", "POST"]
)
def semesters():

    message = ""

    if request.method == "POST":

        # IMPORTANT:
        # This matches name="semester_name"
        # in semesters.html.

        semester_name = request.form.get(
            "semester_name",
            ""
        ).strip()

        if not semester_name:

            message = (
                "Please enter a semester name."
            )

        else:

            existing = Semester.query.filter_by(
                name=semester_name
            ).first()

            if existing:

                message = (
                    "This semester already exists."
                )

            else:

                new_semester = Semester(
                    name=semester_name,
                    is_active=False
                )

                db.session.add(
                    new_semester
                )

                db.session.commit()

                message = (
                    "Semester added successfully!"
                )

    all_semesters = (
        Semester.query
        .order_by(
            Semester.id
        )
        .all()
    )

    active_semester = get_active_semester()

    return render_template(
        "semesters.html",
        semesters=all_semesters,
        active_semester=active_semester,
        message=message
    )


# ============================================================
# SET ACTIVE SEMESTER
# ============================================================

@app.route(
    "/set-active-semester/<int:semester_id>",
    methods=["POST"]
)
def set_active_semester(semester_id):

    semester = Semester.query.get_or_404(
        semester_id
    )

    all_semesters = Semester.query.all()

    for item in all_semesters:

        item.is_active = False

    semester.is_active = True

    db.session.commit()

    return redirect(
        url_for("semesters")
    )


# ============================================================
# DELETE SEMESTER
# ============================================================

@app.route(
    "/delete-semester/<int:semester_id>",
    methods=["POST"]
)
def delete_semester(semester_id):

    semester = Semester.query.get_or_404(
        semester_id
    )

    # Prevent deleting the active semester.
    if semester.is_active:

        return redirect(
            url_for("semesters")
        )

    subjects = Subject.query.filter_by(
        semester_id=semester.id
    ).all()

    for subject in subjects:

        timetable_entries = (
            Timetable.query
            .filter_by(
                subject_id=subject.id
            )
            .all()
        )

        for entry in timetable_entries:

            TimetableChange.query.filter_by(
                timetable_id=entry.id
            ).delete(
                synchronize_session=False
            )

        Attendance.query.filter_by(
            subject_id=subject.id
        ).delete(
            synchronize_session=False
        )

        Timetable.query.filter_by(
            subject_id=subject.id
        ).delete(
            synchronize_session=False
        )

    Subject.query.filter_by(
        semester_id=semester.id
    ).delete(
        synchronize_session=False
    )

    db.session.delete(
        semester
    )

    db.session.commit()

    return redirect(
        url_for("semesters")
    )


# ============================================================
# SUBJECTS
# ============================================================

@app.route(
    "/subjects",
    methods=["GET", "POST"]
)
def subjects():

    message = ""

    active_semester = get_active_semester()

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        subject_type = request.form.get(
            "subject_type",
            ""
        ).strip()

        if not name or not subject_type:

            message = (
                "Please enter the subject name "
                "and select the subject type."
            )

        else:

            existing_subject = Subject.query.filter_by(
                name=name,
                subject_type=subject_type,
                semester_id=active_semester.id
            ).first()

            if existing_subject:

                message = (
                    "This subject already exists "
                    "in the active semester."
                )

            else:

                new_subject = Subject(
                    name=name,
                    subject_type=subject_type,
                    semester_id=active_semester.id
                )

                db.session.add(
                    new_subject
                )

                db.session.commit()

                message = (
                    "Subject added successfully!"
                )

    all_subjects = (
        Subject.query
        .filter_by(
            semester_id=active_semester.id
        )
        .order_by(
            Subject.id
        )
        .all()
    )

    return render_template(
        "subjects.html",
        subjects=all_subjects,
        message=message,
        active_semester=active_semester
    )


# ============================================================
# DELETE SUBJECT
# ============================================================

@app.route(
    "/delete-subject/<int:subject_id>",
    methods=["POST"]
)
def delete_subject(subject_id):

    subject = Subject.query.get_or_404(
        subject_id
    )

    active_semester = get_active_semester()

    if subject.semester_id != active_semester.id:

        return redirect(
            url_for("subjects")
        )

    timetable_entries = Timetable.query.filter_by(
        subject_id=subject.id
    ).all()

    for entry in timetable_entries:

        TimetableChange.query.filter_by(
            timetable_id=entry.id
        ).delete(
            synchronize_session=False
        )

    Timetable.query.filter_by(
        subject_id=subject.id
    ).delete(
        synchronize_session=False
    )

    Attendance.query.filter_by(
        subject_id=subject.id
    ).delete(
        synchronize_session=False
    )

    db.session.delete(
        subject
    )

    db.session.commit()

    return redirect(
        url_for("subjects")
    )


# ============================================================
# TIMETABLE
# ============================================================

@app.route(
    "/timetable",
    methods=["GET", "POST"]
)
def timetable():

    message = ""

    active_semester = get_active_semester()

    subjects_list = (
        Subject.query
        .filter_by(
            semester_id=active_semester.id
        )
        .order_by(
            Subject.name
        )
        .all()
    )

    if request.method == "POST":

        subject_id = request.form.get(
            "subject_id"
        )

        day = request.form.get(
            "day",
            ""
        ).strip()

        start_time = request.form.get(
            "start_time",
            ""
        ).strip()

        end_time = request.form.get(
            "end_time",
            ""
        ).strip()

        if (
            not subject_id
            or not day
            or not start_time
            or not end_time
        ):

            message = (
                "Please fill in all timetable fields."
            )

        elif start_time >= end_time:

            message = (
                "End time must be later than start time."
            )

        else:

            try:

                subject_id_int = int(
                    subject_id
                )

            except ValueError:

                subject_id_int = None

            selected_subject = None

            if subject_id_int is not None:

                selected_subject = (
                    Subject.query.filter_by(
                        id=subject_id_int,
                        semester_id=active_semester.id
                    ).first()
                )

            if not selected_subject:

                message = (
                    "Invalid subject selected."
                )

            else:

                existing = (
                    Timetable.query.filter_by(
                        subject_id=
                            selected_subject.id,
                        day=day,
                        start_time=start_time,
                        end_time=end_time
                    ).first()
                )

                if existing:

                    message = (
                        "This timetable slot already exists."
                    )

                else:

                    entry = Timetable(
                        subject_id=
                            selected_subject.id,
                        day=day,
                        start_time=start_time,
                        end_time=end_time
                    )

                    db.session.add(
                        entry
                    )

                    db.session.commit()

                    message = (
                        "Timetable entry added successfully!"
                    )

    timetable_entries = (
        Timetable.query
        .join(Subject)
        .filter(
            Subject.semester_id ==
                active_semester.id
        )
        .all()
    )

    timetable_entries.sort(
        key=lambda entry: (
            DAY_ORDER.get(
                entry.day,
                99
            ),
            entry.start_time
        )
    )

    return render_template(
        "timetable.html",
        subjects=subjects_list,
        timetable=timetable_entries,
        message=message,
        active_semester=active_semester
    )


# ============================================================
# DELETE TIMETABLE
# ============================================================

@app.route(
    "/delete-timetable/<int:entry_id>",
    methods=["POST"]
)
def delete_timetable(entry_id):

    entry = Timetable.query.get_or_404(
        entry_id
    )

    active_semester = get_active_semester()

    if (
        entry.subject.semester_id
        != active_semester.id
    ):

        return redirect(
            url_for("timetable")
        )

    TimetableChange.query.filter_by(
        timetable_id=entry.id
    ).delete(
        synchronize_session=False
    )

    db.session.delete(
        entry
    )

    db.session.commit()

    return redirect(
        url_for("timetable")
    )


# ============================================================
# TODAY
# ============================================================

@app.route("/today")
def today():

    current_date = datetime.now()

    today_name = current_date.strftime(
        "%A"
    )

    today_date = current_date.strftime(
        "%Y-%m-%d"
    )

    active_semester = get_active_semester()

    effective_classes = get_effective_classes(
        today_date
    )

    today_classes = []

    attendance_status = {}

    for item in effective_classes:

        entry = item["timetable"]

        today_classes.append({
            "id": entry.id,
            "subject": entry.subject,
            "day": item["day"],
            "start_time": item["start_time"],
            "end_time": item["end_time"],
            "changed": item["changed"],
            "change_type":
                item["change_type"]
        })

        record = Attendance.query.filter_by(
            subject_id=entry.subject_id,
            date=today_date
        ).first()

        if record:

            attendance_status[
                entry.id
            ] = record.status

        else:

            attendance_status[
                entry.id
            ] = None

    return render_template(
        "today.html",
        today_name=today_name,
        today_date=today_date,
        today_classes=today_classes,
        attendance_status=attendance_status,
        active_semester=active_semester
    )


# ============================================================
# MARK ATTENDANCE
# ============================================================

@app.route(
    "/mark-attendance/<int:timetable_id>/<status>",
    methods=["POST"]
)
def mark_attendance(
    timetable_id,
    status
):

    entry = Timetable.query.get_or_404(
        timetable_id
    )

    active_semester = get_active_semester()

    if (
        entry.subject.semester_id
        != active_semester.id
    ):

        return redirect(
            url_for("today")
        )

    if status not in [
        "Present",
        "Absent"
    ]:

        return redirect(
            url_for("today")
        )

    today_date = datetime.now().strftime(
        "%Y-%m-%d"
    )

    effective_classes = get_effective_classes(
        today_date
    )

    valid_class = any(
        item["timetable"].id ==
            timetable_id
        for item in effective_classes
    )

    if not valid_class:

        return redirect(
            url_for("today")
        )

    existing_record = Attendance.query.filter_by(
        subject_id=entry.subject_id,
        date=today_date
    ).first()

    if existing_record:

        existing_record.status = status

    else:

        record = Attendance(
            subject_id=entry.subject_id,
            date=today_date,
            status=status
        )

        db.session.add(
            record
        )

    db.session.commit()

    return redirect(
        url_for("today")
    )


# ============================================================
# ATTENDANCE ENTRY
# ============================================================

@app.route(
    "/attendance-entry",
    methods=["GET", "POST"]
)
def attendance_entry():

    active_semester = get_active_semester()

    if not active_semester:

        return "No active semester found."

    selected_date = request.form.get(
        "date",
        ""
    ).strip()

    # --------------------------------------------------------
    # FIRST VISIT
    # --------------------------------------------------------

    if request.method == "GET":

        return render_template(
            "attendance_entry.html",
            active_semester=active_semester,
            classes=[],
            selected_date="",
            message=""
        )

    # --------------------------------------------------------
    # DATE CHECK
    # --------------------------------------------------------

    if not selected_date:

        return render_template(
            "attendance_entry.html",
            active_semester=active_semester,
            classes=[],
            selected_date="",
            message="Please select a date."
        )

    # --------------------------------------------------------
    # CONVERT DATE
    # --------------------------------------------------------

    try:

        attendance_date = datetime.strptime(
            selected_date,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        return render_template(
            "attendance_entry.html",
            active_semester=active_semester,
            classes=[],
            selected_date=selected_date,
            message="Invalid date."
        )

    # --------------------------------------------------------
    # GET EFFECTIVE CLASSES FOR EXACT DATE
    # --------------------------------------------------------

    effective_classes = get_effective_classes(
        attendance_date
    )

    # --------------------------------------------------------
    # NO CLASSES
    # --------------------------------------------------------

    if not effective_classes:

        return render_template(
            "attendance_entry.html",
            active_semester=active_semester,
            classes=[],
            selected_date=selected_date,
            message=(
                "No classes scheduled for this date."
            )
        )

    # --------------------------------------------------------
    # CONVERT TO DISPLAY OBJECTS
    # --------------------------------------------------------

    display_classes = []

    for item in effective_classes:

        original_entry = item["timetable"]

        display_entry = SimpleNamespace(
            id=original_entry.id,
            subject_id=
                original_entry.subject_id,
            subject=original_entry.subject,
            day=item["day"],
            start_time=
                item["start_time"],
            end_time=
                item["end_time"],
            changed=item["changed"],
            change_type=
                item["change_type"]
        )

        display_classes.append(
            display_entry
        )

    # --------------------------------------------------------
    # ONLY LOAD CLASSES
    # --------------------------------------------------------

    if request.form.get(
        "save_attendance"
    ) != "yes":

        return render_template(
            "attendance_entry.html",
            active_semester=active_semester,
            classes=display_classes,
            selected_date=selected_date,
            message=""
        )

    # --------------------------------------------------------
    # SAVE ATTENDANCE
    # --------------------------------------------------------

    for item in effective_classes:

        entry = item["timetable"]

        status = request.form.get(
            f"status_{entry.id}",
            ""
        ).strip()

        # ----------------------------------------------------
        # CANCELLED / POSTPONED
        # ----------------------------------------------------

        if status in [
            "Cancelled",
            "Postponed"
        ]:

            existing_record = (
                Attendance.query.filter_by(
                    subject_id=
                        entry.subject_id,
                    date=selected_date
                ).first()
            )

            if existing_record:

                db.session.delete(
                    existing_record
                )

            continue

        # ----------------------------------------------------
        # ONLY PRESENT / ABSENT SAVED
        # ----------------------------------------------------

        if status not in [
            "Present",
            "Absent"
        ]:

            continue

        # ----------------------------------------------------
        # CHECK EXISTING RECORD
        # ----------------------------------------------------

        existing_record = (
            Attendance.query.filter_by(
                subject_id=entry.subject_id,
                date=selected_date
            ).first()
        )

        if existing_record:

            existing_record.status = status

        else:

            new_record = Attendance(
                subject_id=
                    entry.subject_id,
                date=selected_date,
                status=status
            )

            db.session.add(
                new_record
            )

    db.session.commit()

    return render_template(
        "attendance_entry.html",
        active_semester=active_semester,
        classes=display_classes,
        selected_date=selected_date,
        message=(
            "Attendance saved successfully!"
        )
    )


# ============================================================
# ATTENDANCE SUMMARY
# ============================================================

@app.route("/attendance")
def attendance():

    active_semester = get_active_semester()

    subjects = (
        Subject.query
        .filter_by(
            semester_id=active_semester.id
        )
        .order_by(
            Subject.name,
            Subject.subject_type
        )
        .all()
    )

    summary = []

    total_classes = 0

    total_present = 0

    for subject in subjects:

        records = Attendance.query.filter_by(
            subject_id=subject.id
        ).all()

        classes = len(records)

        present = sum(
            1
            for record in records
            if record.status == "Present"
        )

        percentage = (
            (present / classes) * 100
            if classes > 0
            else 0
        )

        total_classes += classes

        total_present += present

        summary.append({
            "subject": subject,
            "classes": classes,
            "present": present,
            "absent":
                classes - present,
            "percentage": round(
                percentage,
                2
            )
        })

    overall_percentage = (
        (total_present /
         total_classes) * 100
        if total_classes > 0
        else 0
    )

    return render_template(
        "attendance.html",
        summary=summary,
        total_classes=total_classes,
        total_present=total_present,
        overall_percentage=round(
            overall_percentage,
            2
        ),
        active_semester=active_semester
    )


# ============================================================
# ATTENDANCE HISTORY
# ============================================================

@app.route("/attendance-history")
def attendance_history():

    active_semester = get_active_semester()

    records = (
        Attendance.query
        .join(Subject)
        .filter(
            Subject.semester_id ==
                active_semester.id
        )
        .order_by(
            Attendance.date.desc(),
            Attendance.id.desc()
        )
        .all()
    )

    return render_template(
        "attendance_history.html",
        records=records,
        active_semester=active_semester
    )


# ============================================================
# DELETE ATTENDANCE
# ============================================================

@app.route(
    "/delete-attendance/<int:record_id>",
    methods=["POST"]
)
def delete_attendance(record_id):

    record = Attendance.query.get_or_404(
        record_id
    )

    active_semester = get_active_semester()

    if (
        record.subject.semester_id
        != active_semester.id
    ):

        return redirect(
            url_for("attendance_history")
        )

    db.session.delete(
        record
    )

    db.session.commit()

    return redirect(
        url_for("attendance_history")
    )


# ============================================================
# 75% PLANNER
# ============================================================

@app.route("/planner")
def planner():

    active_semester = get_active_semester()

    subjects = (
        Subject.query
        .filter_by(
            semester_id=active_semester.id
        )
        .order_by(
            Subject.name,
            Subject.subject_type
        )
        .all()
    )

    planner_data = []

    for subject in subjects:

        records = Attendance.query.filter_by(
            subject_id=subject.id
        ).all()

        total = len(records)

        present = sum(
            1
            for record in records
            if record.status == "Present"
        )

        absent = total - present

        if total == 0:

            planner_data.append({
                "subject": subject,
                "total": 0,
                "present": 0,
                "absent": 0,
                "percentage": 0,
                "status":
                    "No Classes Recorded",
                "classes_to_attend": 0,
                "classes_can_miss": 0
            })

            continue

        percentage = (
            present / total
        ) * 100

        if percentage >= 75:

            classes_can_miss = math.floor(
                (present / 0.75) - total
            )

            if classes_can_miss < 0:

                classes_can_miss = 0

            classes_to_attend = 0

            status = "SAFE"

        else:

            required_classes = (
                (0.75 * total - present)
                / 0.25
            )

            classes_to_attend = math.ceil(
                required_classes
            )

            classes_can_miss = 0

            status = "BELOW 75%"

        planner_data.append({
            "subject": subject,
            "total": total,
            "present": present,
            "absent": absent,
            "percentage":
                round(percentage, 2),
            "status": status,
            "classes_to_attend":
                classes_to_attend,
            "classes_can_miss":
                classes_can_miss
        })

    return render_template(
        "planner.html",
        planner_data=planner_data,
        active_semester=active_semester
    )


# ============================================================
# TIMETABLE CHANGES
# ============================================================

@app.route(
    "/timetable-changes",
    methods=["GET", "POST"]
)
def timetable_changes():

    message = ""

    active_semester = get_active_semester()

    timetable_entries = (
        Timetable.query
        .join(Subject)
        .filter(
            Subject.semester_id ==
                active_semester.id
        )
        .order_by(
            Timetable.id
        )
        .all()
    )

    if request.method == "POST":

        timetable_id = request.form.get(
            "timetable_id"
        )

        change_date = request.form.get(
            "change_date",
            ""
        ).strip()

        change_type = request.form.get(
            "change_type",
            ""
        ).strip()

        new_day = request.form.get(
            "new_day",
            ""
        ).strip()

        new_start_time = request.form.get(
            "new_start_time",
            ""
        ).strip()

        new_end_time = request.form.get(
            "new_end_time",
            ""
        ).strip()

        reason = request.form.get(
            "reason",
            ""
        ).strip()

        if (
            not timetable_id
            or not change_date
            or not change_type
        ):

            message = (
                "Please select the class, "
                "date and change type."
            )

        else:

            try:

                timetable_id_int = int(
                    timetable_id
                )

            except ValueError:

                timetable_id_int = None

            timetable_entry = None

            if timetable_id_int is not None:

                timetable_entry = (
                    Timetable.query.get(
                        timetable_id_int
                    )
                )

            if not timetable_entry:

                message = (
                    "Selected timetable entry "
                    "was not found."
                )

            elif (
                timetable_entry.subject.semester_id
                != active_semester.id
            ):

                message = (
                    "Selected class does not "
                    "belong to the active semester."
                )

            elif change_type in [
                "Rescheduled",
                "Shifted"
            ]:

                if (
                    not new_day
                    or not new_start_time
                    or not new_end_time
                ):

                    message = (
                        "Please enter the new day "
                        "and new start/end time."
                    )

                elif new_start_time >= new_end_time:

                    message = (
                        "New end time must be later "
                        "than new start time."
                    )

                else:

                    change = TimetableChange(
                        timetable_id=
                            timetable_entry.id,
                        change_date=
                            change_date,
                        change_type=
                            change_type,
                        new_day=new_day,
                        new_start_time=
                            new_start_time,
                        new_end_time=
                            new_end_time,
                        reason=reason
                    )

                    db.session.add(
                        change
                    )

                    db.session.commit()

                    message = (
                        "Timetable change "
                        "saved successfully!"
                    )

            elif change_type in [
                "Cancelled",
                "Postponed"
            ]:

                change = TimetableChange(
                    timetable_id=
                        timetable_entry.id,
                    change_date=
                        change_date,
                    change_type=
                        change_type,
                    reason=reason
                )

                db.session.add(
                    change
                )

                db.session.commit()

                message = (
                    "Timetable change "
                    "saved successfully!"
                )

            else:

                message = (
                    "Invalid timetable change type."
                )

    changes = (
        TimetableChange.query
        .join(Timetable)
        .join(Subject)
        .filter(
            Subject.semester_id ==
                active_semester.id
        )
        .order_by(
            TimetableChange.id.desc()
        )
        .all()
    )

    return render_template(
        "timetable_changes.html",
        timetable_entries=timetable_entries,
        changes=changes,
        message=message,
        active_semester=active_semester
    )


# ============================================================
# DELETE TIMETABLE CHANGE
# ============================================================

@app.route(
    "/delete-timetable-change/<int:change_id>",
    methods=["POST"]
)
def delete_timetable_change(change_id):

    change = TimetableChange.query.get_or_404(
        change_id
    )

    active_semester = get_active_semester()

    if (
        change.timetable.subject.semester_id
        != active_semester.id
    ):

        return redirect(
            url_for("timetable_changes")
        )

    db.session.delete(
        change
    )

    db.session.commit()

    return redirect(
        url_for("timetable_changes")
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

with app.app_context():

    db.create_all()

    ensure_database_columns()

    get_active_semester()


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
