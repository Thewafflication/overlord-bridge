"""Request-local worker routing within the already admitted free model pool."""
from dataclasses import dataclass


LEVELS = {"routine", "standard", "complex"}
# Conservative preferences, not benchmark claims. Unknown catalog models stay
# eligible between known reasoning choices and known lightweight choices.
REASONING = {"gpt-oss-120b", "nemotron-3-super-120b-a12b",
             "nemotron-3-ultra-550b-a55b"}
LIGHTWEIGHT = {"gpt-oss-20b", "nemotron-3.5-lightning-30b-a3b",
               "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
               "gemini-2.5-flash-lite"}


def family(key):
    return key.split(":", 1)[-1].removesuffix(":free").split("/")[-1]


@dataclass(frozen=True)
class WorkerRouting:
    difficulty: str = "unknown"
    phase: str = "execute"
    escalated: bool = False
    previous_model: str = ""

    @property
    def reasoning(self):
        return self.phase in {"plan", "review"} or self.escalated or self.difficulty != "routine"

    def rank(self, spec):
        model = family(spec.key)
        tier = 0 if model in REASONING else (2 if model in LIGHTWEIGHT else 1)
        if not self.reasoning:
            tier = 2 - tier
        same_reviewer = self.phase == "review" and model == family(self.previous_model)
        return tier, same_reviewer


class RoutedMessages(list):
    pass


def route_request(messages, routing):
    # Preserve BudgetedMessages.fit and all protected-context fitting rules.
    if not hasattr(messages, "__dict__"):
        messages = RoutedMessages(messages)
    messages.worker_routing = routing
    return messages
