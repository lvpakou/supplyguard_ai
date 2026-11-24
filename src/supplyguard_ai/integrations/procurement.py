from supplyguard_ai.state import Action, ExecutionResult

_DONE: dict[str, tuple[Action, ExecutionResult]] = {}


def execute(
    action: Action,
    approval_id: str | None,
    idempotency_key: str
) -> ExecutionResult:

    if not idempotency_key:
        return ExecutionResult(
            operation=action.operation,
            idempotency_key=idempotency_key,
            status="refused",
            message="idempotency_key is required"
        )

    if idempotency_key in _DONE:
        previous_action, first_result = _DONE[idempotency_key]

        if previous_action != action:
            return ExecutionResult(
                operation=action.operation,
                idempotency_key=idempotency_key,
                status="refused",
                message="idempotency key was already used for a different action"
            )

        return first_result.model_copy(update={"status": "already_done"})

    if not approval_id:
        return ExecutionResult(
            operation=action.operation,
            idempotency_key=idempotency_key,
            status="refused",
            message="write operations require an approval_id"
        )

    result = ExecutionResult(
        operation=action.operation,
        idempotency_key=idempotency_key,
        status="done",
        reference=f"SIM-{len(_DONE) + 1:04d}",
        message="STUB: simulated"
    )

    _DONE[idempotency_key] = (action, result)

    return result