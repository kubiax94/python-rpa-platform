from __future__ import annotations

from dataclasses import dataclass

from vm_agent_server.src.settings.models import IdentityAccessSettings, IdentitySettings
from vm_agent_server.src.users.helpers import clean_str


@dataclass(slots=True)
class IdentityAccessDecision:
    allow_login: bool
    agent_visibility: str


def is_subject_or_group_allowed(access: IdentityAccessSettings, subject: str, group_ids: list[str], matched_mapping_ids: set[str]) -> bool:
    allowed_subjects = {clean_str(str(item)) for item in access.allowed_user_subjects if clean_str(str(item))}
    if subject in allowed_subjects:
        return True

    allowed_groups = {clean_str(str(item)) for item in access.allowed_group_ids if clean_str(str(item))}
    if allowed_groups.intersection(group_ids):
        return True

    if access.allow_mapped_groups and matched_mapping_ids:
        return True

    return False


def evaluate_identity_access(identity: IdentitySettings, subject: str, group_ids: list[str], matched_mapping_ids: set[str]) -> IdentityAccessDecision:
    access = identity.access if isinstance(identity.access, IdentityAccessSettings) else IdentityAccessSettings()
    if access.mode == "allow_all":
        return IdentityAccessDecision(allow_login=True, agent_visibility="all")

    is_allowed = is_subject_or_group_allowed(access, subject, group_ids, matched_mapping_ids)
    if access.mode == "deny_unlisted":
        return IdentityAccessDecision(allow_login=is_allowed, agent_visibility="all" if is_allowed else "none")

    if access.mode == "allow_limited":
        return IdentityAccessDecision(allow_login=True, agent_visibility="all" if is_allowed else "none")

    return IdentityAccessDecision(allow_login=True, agent_visibility="all")