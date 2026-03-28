from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

TASK_KIND_AGENT = "agent"
TASK_KIND_DEPLOYMENT = "deployment"


@dataclass(frozen=True, slots=True)
class TaskComponent:
    type: str
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "config": dict(self.config),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "TaskComponent":
        if not isinstance(raw, dict):
            raise TypeError("Task component must be a dict")

        component_type = str(raw.get("type") or "generic")
        config = raw.get("config")
        if not isinstance(config, dict):
            config = {}

        return cls(type=component_type, config=config)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    id: str
    kind: str
    agent_id: str
    script: str
    name: str = ""
    cwd: str = ""
    timeout_sec: int = 300
    session: str = ""
    pipeline_run_id: str | None = None
    step_index: int = 0
    requested_by: str = "system"
    requested_from: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    components: tuple[TaskComponent, ...] = field(default_factory=tuple)

    def to_api_dict(self, *, status: str = "queued", created_at: int | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "pipeline_run_id": self.pipeline_run_id,
            "step_index": self.step_index,
            "agent_id": self.agent_id,
            "session": self.session,
            "name": self.name,
            "script": self.script,
            "cwd": self.cwd,
            "timeout_sec": self.timeout_sec,
            "config_id": None,
            "status": status,
            "pid": None,
            "exit_code": None,
            "error": None,
            "requested_by": self.requested_by,
            "requested_from": self.requested_from,
            "created_at": created_at,
            "started_at": None,
            "completed_at": None,
            "kind": self.kind,
            "payload": dict(self.payload),
            "components": [component.to_dict() for component in self.components],
        }

    def get_component(self, component_type: str) -> TaskComponent | None:
        for component in self.components:
            if component.type == component_type:
                return component
        return None

    def as_agent_execution(self) -> dict[str, Any] | None:
        component = self.get_component("execution")
        if component is None:
            return None

        env = component.config.get("env")
        if not isinstance(env, dict):
            env = {}

        return {
            "task_id": self.id,
            "script": str(component.config.get("script") or self.script),
            "cwd": str(component.config.get("cwd") or self.cwd),
            "timeout_sec": int(component.config.get("timeout_sec") or self.timeout_sec),
            "session": str(component.config.get("session") or self.session),
            "env": env,
        }


@dataclass(frozen=True, slots=True)
class AgentTaskSpec(TaskSpec):
    def __post_init__(self):
        if self.kind != TASK_KIND_AGENT:
            raise ValueError(f"AgentTaskSpec requires kind={TASK_KIND_AGENT}")
        if self.get_component("execution") is None:
            raise ValueError("AgentTaskSpec requires an execution component")

    @classmethod
    def from_task_spec(cls, task: TaskSpec) -> "AgentTaskSpec":
        return cls(
            id=task.id,
            kind=task.kind,
            agent_id=task.agent_id,
            script=task.script,
            name=task.name,
            cwd=task.cwd,
            timeout_sec=task.timeout_sec,
            session=task.session,
            pipeline_run_id=task.pipeline_run_id,
            step_index=task.step_index,
            requested_by=task.requested_by,
            requested_from=task.requested_from,
            payload=dict(task.payload),
            components=tuple(task.components),
        )

    @property
    def execution(self) -> dict[str, Any]:
        execution = self.as_agent_execution()
        if execution is None:
            raise ValueError(f"Task {self.id} does not have an execution component")
        return execution


@dataclass(frozen=True, slots=True)
class DeploymentTaskSpec(TaskSpec):
    def __post_init__(self):
        if self.kind != TASK_KIND_DEPLOYMENT:
            raise ValueError(f"DeploymentTaskSpec requires kind={TASK_KIND_DEPLOYMENT}")
        if self.get_component("deployment") is None:
            raise ValueError("DeploymentTaskSpec requires a deployment component")

    @classmethod
    def from_task_spec(cls, task: TaskSpec) -> "DeploymentTaskSpec":
        return cls(
            id=task.id,
            kind=task.kind,
            agent_id=task.agent_id,
            script=task.script,
            name=task.name,
            cwd=task.cwd,
            timeout_sec=task.timeout_sec,
            session=task.session,
            pipeline_run_id=task.pipeline_run_id,
            step_index=task.step_index,
            requested_by=task.requested_by,
            requested_from=task.requested_from,
            payload=dict(task.payload),
            components=tuple(task.components),
        )

    @property
    def operation(self) -> str:
        return str(self.payload.get("operation") or self.script)

    @property
    def deployment(self) -> dict[str, Any]:
        component = self.get_component("deployment")
        if component is None:
            raise ValueError(f"Task {self.id} does not have a deployment component")
        return dict(component.config)


class TaskBuilder:
    def __init__(self, *, agent_id: str, kind: str, script: str, task_id: str | None = None):
        self._task_id = task_id or uuid4().hex
        self._kind = kind
        self._agent_id = agent_id
        self._script = script
        self._name = ""
        self._cwd = ""
        self._timeout_sec = 300
        self._session = ""
        self._pipeline_run_id: str | None = None
        self._step_index = 0
        self._requested_by = "system"
        self._requested_from = ""
        self._payload: dict[str, Any] = {}
        self._components: dict[str, TaskComponent] = {}

    @classmethod
    def agent(cls, agent_id: str, script: str, *, task_id: str | None = None) -> "TaskBuilder":
        return cls(agent_id=agent_id, kind=TASK_KIND_AGENT, script=script, task_id=task_id).component(
            "execution",
            script=script,
            cwd="",
            timeout_sec=300,
            session="",
            env={},
        )

    @classmethod
    def deployment(cls, agent_id: str, operation: str, *, task_id: str | None = None) -> "TaskBuilder":
        return (
            cls(agent_id=agent_id, kind=TASK_KIND_DEPLOYMENT, script=operation, task_id=task_id)
            .payload_field("operation", operation)
            .component("deployment", operation=operation)
        )

    def name(self, value: str) -> "TaskBuilder":
        self._name = value
        return self

    def cwd(self, value: str) -> "TaskBuilder":
        self._cwd = value
        if "execution" in self._components:
            self.component("execution", cwd=value)
        return self

    def timeout(self, value: int) -> "TaskBuilder":
        self._timeout_sec = value
        if "execution" in self._components:
            self.component("execution", timeout_sec=value)
        return self

    def session(self, value: str) -> "TaskBuilder":
        self._session = value
        if "execution" in self._components:
            self.component("execution", session=value)
        return self

    def pipeline(self, run_id: str | None, step_index: int) -> "TaskBuilder":
        self._pipeline_run_id = run_id
        self._step_index = step_index
        if run_id:
            self.component("pipeline", run_id=run_id, step_index=step_index)
        return self

    def requested_by(self, value: str) -> "TaskBuilder":
        self._requested_by = value
        return self

    def requested_from(self, value: str) -> "TaskBuilder":
        self._requested_from = value
        return self

    def payload_field(self, key: str, value: Any) -> "TaskBuilder":
        self._payload[key] = value
        return self

    def env(self, value: dict[str, Any] | None) -> "TaskBuilder":
        return self.component("execution", env=value or {})

    def component(self, component_type: str, **config: Any) -> "TaskBuilder":
        existing = self._components.get(component_type)
        merged_config = dict(existing.config) if existing else {}
        merged_config.update(config)
        self._components[component_type] = TaskComponent(type=component_type, config=merged_config)
        return self

    def build(self) -> TaskSpec:
        task = TaskSpec(
            id=self._task_id,
            kind=self._kind,
            agent_id=self._agent_id,
            script=self._script,
            name=self._name,
            cwd=self._cwd,
            timeout_sec=self._timeout_sec,
            session=self._session,
            pipeline_run_id=self._pipeline_run_id,
            step_index=self._step_index,
            requested_by=self._requested_by,
            requested_from=self._requested_from,
            payload=dict(self._payload),
            components=tuple(self._components.values()),
        )
        if task.kind == TASK_KIND_AGENT:
            return AgentTaskSpec.from_task_spec(task)
        if task.kind == TASK_KIND_DEPLOYMENT:
            return DeploymentTaskSpec.from_task_spec(task)
        return task