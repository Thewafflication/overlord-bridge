"""Structured model assessment of whether a free worker has useful work.

The model interprets requirements; Python enforces the resulting admission
state and read-only discovery budget, not a vocabulary of task keywords.
"""

STATES = ("ready", "discovery", "needs_planning", "blocked", "already_complete")
FIELDS = ("state", "requirement", "deliverable", "acceptance", "evidence", "reason")
DISCOVERY_ACTIONS = 6
READ_TOOLS = frozenset({"read_file", "list_files", "search_file", "update_plan"})
SCHEMA = {
    "type": "object",
    "properties": {
        key: ({"type": "string", "enum": list(STATES)} if key == "state" else
              {"type": "string", "maxLength": 1000}) for key in FIELDS
    },
    "required": list(FIELDS), "additionalProperties": False,
}
INSTRUCTION = (
    "Include readiness with state, requirement, deliverable, acceptance, evidence and reason. "
    "Interpret the actual owner request and current evidence, not task keywords. "
    "ready requires an authorized unfinished requirement, a bounded useful outcome, an exact "
    "acceptance command or observable check, and evidence explaining why it remains undone. "
    "Documentation work can be useful when the owner requested it; generic record maintenance, "
    "historical HEAD refreshes, rereading files, placeholder tests or already completed repairs "
    "are not a new product deliverable. Do not invent requirements to justify activity. "
    "If evidence is insufficient, choose discovery and identify the specific missing fact. "
    "Discovery permits at most six file read/search/list or plan actions, no commands or writes, "
    "then one reassessment; its allowance cannot be renewed. If no useful plan can be established, "
    "choose needs_planning and name the missing owner decision. Use blocked for a concrete "
    "prerequisite preventing progress, or already_complete for verified prior work without "
    "another authorized deliverable. These states yield unfinished work, never a success claim. "
    "At a progress checkpoint after actually performing the admitted work, retain ready to "
    "submit completed steps through the existing finish_task and independent acceptance review. "
    "Do not invent test results, source locations or owner approval. "
)


def issues(value, required=False):
    if value is None and not required:
        return []
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        return ["readiness requires exactly state, requirement, deliverable, acceptance, evidence and reason"]
    errors = []
    if value["state"] not in STATES:
        errors.append("readiness.state is not recognized")
    for key in FIELDS[1:]:
        if not isinstance(value[key], str) or len(value[key]) > 1000:
            errors.append(f"readiness.{key} must be a string of at most 1000 characters")
        elif (key in ("evidence", "reason") or value["state"] == "ready") and not value[key].strip():
            errors.append(f"readiness.{key} must explain the actual task")
    return errors
