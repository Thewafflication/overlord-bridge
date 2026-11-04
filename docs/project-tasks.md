# Project task queues

The bridge reads owner-maintained `run/project-tasks.json` at the start of each
free project worker. Package updates preserve this file. The queue has version
1 and a `tasks` array. Each task names its absolute project folder, stable ID,
state (`ready` or `completed`), requirement, bounded task description and between
one and twelve checks. Each check supplies a name, a `run_command` or `run_python`
tool and its normal arguments. The earliest ready task for the project is used.
Projects without queue entries continue using their existing dispatch tasks.

The owner controls the commands. They run through the existing command tools
and approval policy. The worker receives the full definition before planning.
Checks execute before recognizable ordinary `git push` commands and again on
proposed completion. Exit zero, successful execution and absence of timeout are
required. A failed check rejects completion even when the model reviewer says
complete. Reports include the task ID, check outcomes and bounded redacted output.

An optional `publication` object names `remote`, `branch` and the owned `paths`.
Completion requires those paths to match HEAD and the actual remote branch SHA
to equal the validated HEAD. These checks run at completion, after the worker has
committed and pushed. The model reviewer continues assessing relevance and scope.

After accepted completion, the task becomes completed using atomic replacement.
If the owner changed the task during execution, completion requires review and
the changed queue is preserved. A configured project with no ready task produces
a skipped report without calling a model. Add the next bounded task to resume it.

The initial WSH pilot names the published public-header regression, compiles its
existing header-hygiene test, runs the documented CMake build/test workflow and
checks publication to origin/master. It also checks hashes of the existing
acceptance tests and build definitions, preserving the validation requirements.
Missing build prerequisites produce a failed acceptance check with its output.
The monitor supplies these concrete findings to the existing project schedule.

This gate covers completion and recognizable direct Git push tool commands.
Arbitrary Python or shell wrappers can execute other operations. This mechanism
does not sandbox project code or prove that an owner-selected test is sufficient.
The rollout starts with WSH so its results can guide task definitions for the
remaining projects.
