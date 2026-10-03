"""Inputs and results exchanged between the eval workflows and their activities."""

from typing import Any

from pydantic import BaseModel

CLAIM_TRIALS = "eval_claim_trials"
START_TRIAL = "eval_start_trial"
POLL_TRIAL = "eval_poll_trial"
FINALIZE_RUN = "eval_finalize_run"
EVALUATE_EXPERIMENT = "eval_evaluate_experiment"
STOP_EXPERIMENT = "eval_stop_experiment"


class EvalRunInput(BaseModel):
    run_id: str
    user_context_data: dict[str, Any]
    concurrency: int
    poll_seconds: int = 15
    trial_timeout_seconds: int = 1800


class ClaimRequest(BaseModel):
    run_id: str
    user_context_data: dict[str, Any]
    limit: int


class TrialRequest(BaseModel):
    trial_id: str
    user_context_data: dict[str, Any]


class StartedTrial(BaseModel):
    trial_id: str
    task_id: str | None = None
    error: str | None = None


class PollRequest(BaseModel):
    trial_id: str
    task_id: str
    user_context_data: dict[str, Any]
    elapsed_seconds: int
    timeout_seconds: int


class PollResult(BaseModel):
    done: bool


class RunRequest(BaseModel):
    run_id: str
    user_context_data: dict[str, Any]


class ExperimentMonitorInput(BaseModel):
    agent_id: str
    experiment_id: str
    user_context_data: dict[str, Any]
    interval_seconds: int = 600
    evaluations_before_continue_as_new: int = 200


class ExperimentRequest(BaseModel):
    agent_id: str
    experiment_id: str
    user_context_data: dict[str, Any]


class ExperimentState(BaseModel):
    running: bool


class StopExperimentRequest(BaseModel):
    agent_id: str
    experiment_id: str
    user_context_data: dict[str, Any]
    reason: str
