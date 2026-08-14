from typing import Literal, TypedDict

StepKeys = Literal[
    "papi_tiktok-connection-info_reached",
    "papi_tiktok-connect_dispatched",
    "papi_callback_reached",
    "papi_await-view_reached",
    "papi_donation_reached",
    "dlul_donation_reached",
    "questionnaire_reached",
    "debriefing_reached",
    "switched_to_dlul",
]

ExceptionKeys = Literal[
    "data-types",
    "download-failed",
    "request-expired",
    "no-request",
    "oath-failed",
]

ParticipationModes = Literal[
    "PAPI",
    "DLUL",
]


class ParticipantLog(TypedDict):
    modes: dict[ParticipationModes, str]
    steps: dict[StepKeys, str]
    errors: dict[ExceptionKeys, str]
