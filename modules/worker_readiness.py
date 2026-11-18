"""Structured model assessment of whether a free worker has useful work.

The model interprets requirements; Python enforces the resulting admission
state and read-only discovery budget, not a vocabulary of task keywords.
"""

STATES = ("ready", "discovery", "needs_planning", "blocked", "already_complete")
FIELDS = ("state", "requirement", "deliverable", "acceptance", "evidence", "reason")
DISCOVERY_ACTIONS = 6
READ_TOOLS = frozenset({"read_file", "list_files", "search_file", "update_plan", "memory_search", "memory_read"})
SCHEMA = {
    "type": "object",
    "properties": {
        key: ({"type": "string", "enum": list(STATES)} if key == "state" else
              {"type": "string", "maxLength": 1000}) for key in FIELDS
    },
    "required": list(FIELDS), "additionalProperties": False,
}
REVIEW_SCHEMA = {**SCHEMA, "properties": {**SCHEMA["properties"], "owner_question": {
    "type": "string", "maxLength": 1000,
    "description": "The question only the owner can resolve. Required to confirm needs_planning.",
}, "next_action": {
    "type": "string", "maxLength": 1000,
    "description": "Useful authorized technical action still possible without owner input. "
                   "Required when reviewing needs_planning; empty only if none exists.",
}}}
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
    "Assess readiness to perform the plan, not whether it has already been executed. "
    "A known failing build or unread source is normally the subject of authorized work: "
    "choose ready for bounded diagnosis/repair, or discovery for missing file evidence. "
    "needs_planning means a specific missing owner requirement or decision prevents selecting useful work. "
)

REVIEW_INSTRUCTION = (
    "You are now independently reviewing a proposed early stop, not completing the project. "
    "Reconcile the original owner task, supplied acceptance queue, current evidence and proposed readiness. "
    "Do not accept a stop just because actions have not run, files need reading, tests fail, or a technical "
    "cause needs diagnosis: those can be the authorized deliverable. Return ready with bounded pending "
    "steps when the task is already defined; use discovery only if its existing six-action budget permits. "
    "Confirm needs_planning only for an actual missing owner requirement/decision; blocked for an external "
    "prerequisite preventing useful authorized progress; already_complete only for verified prior work "
    "with no further authorized deliverable. Never invent a task, evidence, approval or successful test. "
    "Do not weaken acceptance checks, renew discovery, execute tools or claim project completion. "
    "To confirm needs_planning, supply readiness.owner_question with the actual question for the owner. "
    "Also supply readiness.next_action: identify useful authorized work possible before that answer, "
    "including running supplied checks or investigating their failures. If any exists, name it and "
    "return ready with that action in the plan. Only an empty next_action can confirm needs_planning. "
    "A question about observed test results, current source or how to implement an already authorized "
    "requirement is technical work, not a missing owner decision. Do not leave next_action empty "
    "merely because you have not executed the action during this review. "
    "If you can choose the next technical action yourself, return ready with that action. "
    "Return one update_plan assessment; a confirmed early stop will be honored. "
)


def issues(value, required=False):
    if value is None and not required:
        return []
    if not isinstance(value, dict) or set(value) - {"owner_question", "next_action"} != set(FIELDS):
        return ["readiness requires state, requirement, deliverable, acceptance, evidence and reason; owner_question and next_action are optional"]
    errors = []
    if "owner_question" in value and (
        not isinstance(value["owner_question"], str) or len(value["owner_question"]) > 1000
    ):
        errors.append("readiness.owner_question must be a string of at most 1000 characters")
    if "next_action" in value and (
        not isinstance(value["next_action"], str) or len(value["next_action"]) > 1000
    ):
        errors.append("readiness.next_action must be a string of at most 1000 characters")
    if value["state"] not in STATES:
        errors.append("readiness.state is not recognized")
    for key in FIELDS[1:]:
        if not isinstance(value[key], str) or len(value[key]) > 1000:
            errors.append(f"readiness.{key} must be a string of at most 1000 characters")
        elif (key in ("evidence", "reason") or value["state"] == "ready") and not value[key].strip():
            errors.append(f"readiness.{key} must explain the actual task")
    return errors


def review_issues(value):
    """Enforce a model's explicit actionability assessment, without classifying prose."""
    errors = issues(value, required=True)
    if errors or value["state"] != "needs_planning":
        return errors
    if not value.get("owner_question", "").strip():
        errors.append("Confirm needs_planning only with a specific readiness.owner_question. "
                      "If no owner input is needed, select ready and plan the next action.")
    if "next_action" not in value:
        errors.append("Supply readiness.next_action with useful authorized work possible before the owner answers; "
                      "use an empty string only if no such action exists.")
    elif value["next_action"].strip():
        errors.append("readiness.next_action identifies available authorized work; select ready and put that "
                      "action in the plan instead of confirming needs_planning.")
    return errors


def owner_contract(task):
    """The owner's explicit ready queue supplies admission, never completion."""
    return {"state": "ready", "requirement": task["requirement"][:1000],
            "deliverable": task["task"][:1000],
            "acceptance": "; ".join(check["name"] for check in task["checks"])[:1000],
            "evidence": "Owner queue task " + task["id"] + " is ready; run check_acceptance for current observed results.",
            "reason": "Owner-defined executable task; pending diagnosis is authorized work. Completion requires independent acceptance."}
