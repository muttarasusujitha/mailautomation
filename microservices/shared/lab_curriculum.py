"""Consistent module-aware lab scope for planning and costing."""
import json

LOCAL_TERMS = ('local machine', 'localhost', 'docker desktop', 'local lab')


def lab_units(day):
    modules = day.get('modules')
    return [m for m in modules if isinstance(m, dict)] if modules else [day]


def unit_text(unit):
    # Ignore source metadata, review comments and example histories: they are
    # not requested infrastructure. Retain legacy session content.
    fields = ('title', 'topic', 'focus_area', 'category', 'tools', 'lab', 'lab_task',
              'subtopics', 'morning_session', 'afternoon_session')
    return json.dumps({key: unit.get(key) for key in fields}, default=str).lower()


def local_unit(unit):
    return unit.get('lab_setup') == 'local' or any(term in unit_text(unit) for term in LOCAL_TERMS)


def cloud_lab_text(day):
    if day.get('lab_setup') == 'local':
        return ''
    return ' '.join(unit_text(unit) for unit in lab_units(day) if not local_unit(unit))


def lab_setup_kind(day):
    if day.get('lab_setup'):
        return day['lab_setup']
    local = [local_unit(unit) for unit in lab_units(day)]
    return 'local' if local and all(local) else 'mixed' if any(local) else None
