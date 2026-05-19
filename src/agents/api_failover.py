from __future__ import annotations

import os
import re
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.config import AgentSettings, LlmLockSettings, Settings
from src.logger import logger
from src.storage.repository import ArenaRepository


_BILLING_PATTERNS = (
    r"billing error",
    r"run out of credits",
    r"insufficient balance",
    r"\b401\b",
    r"\b402\b",
    r"\b403\b",
    r"auth issue",
    r"rate limit",
    r"timeout",
    r"provider outage",
    r"FailoverError",
)


@dataclass
class ActiveRoute:
    provider: str
    model: str
    base_url: str
    api_key_env: str
    using_fallback: bool
    fallback_index: int


class ApiFailoverManager:
    def __init__(self, settings: Settings, repository: ArenaRepository) -> None:
        self.settings = settings
        self.repository = repository

    def enabled_for(self, agent: AgentSettings) -> bool:
        return self.settings.risk_automation.api_failover.enabled and agent.api_failover.enabled

    def active_route(self, agent: AgentSettings) -> ActiveRoute:
        state = self.repository.get_agent_failover_state(agent.id)
        if state and state.using_fallback:
            chain = agent.api_failover.fallback_chain
            index = max(0, min(state.fallback_index, len(chain) - 1)) if chain else -1
            if chain and index >= 0:
                route = chain[index]
                return ActiveRoute(
                    provider=route.provider,
                    model=route.model,
                    base_url=route.LLM_BASE_URL,
                    api_key_env=route.LLM_API_KEY,
                    using_fallback=True,
                    fallback_index=index,
                )
        return ActiveRoute(
            provider=agent.provider,
            model=agent.model,
            base_url=agent.llm.LLM_BASE_URL,
            api_key_env=agent.llm.LLM_API_KEY,
            using_fallback=False,
            fallback_index=-1,
        )

    def settings_for_route(self, agent: AgentSettings, route: ActiveRoute) -> AgentSettings:
        if not route.using_fallback:
            return agent
        return agent.model_copy(
            update={
                "llm": LlmLockSettings(
                    LLM_PROVIDER=route.provider,
                    LLM_MODEL=route.model,
                    LLM_BASE_URL=route.base_url,
                    LLM_API_KEY=route.api_key_env,
                    LLM_ALLOW_FALLBACK=False,
                )
            }
        )

    def is_failover_error(self, message: str) -> bool:
        text = message.lower()
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _BILLING_PATTERNS)

    def handle_failure(self, agent: AgentSettings, error_message: str) -> ActiveRoute | None:
        if not self.enabled_for(agent) or not self.is_failover_error(error_message):
            return None
        chain = agent.api_failover.fallback_chain
        if not chain:
            return None
        state = self.repository.get_agent_failover_state(agent.id)
        current_index = state.fallback_index if state else -1
        primary_provider = state.primary_provider if state else agent.provider
        primary_model = state.primary_model if state else agent.model
        from_provider = state.active_provider if state and state.using_fallback else agent.provider
        from_model = state.active_model if state and state.using_fallback else agent.model
        next_index = current_index + 1
        if next_index >= len(chain):
            logger.warning("no more failover routes for {}", agent.id)
            return None
        route = chain[next_index]
        self.repository.upsert_agent_failover_state(
            agent.id,
            active_provider=route.provider,
            active_model=route.model,
            primary_provider=primary_provider,
            primary_model=primary_model,
            using_fallback=True,
            primary_available=False,
            fallback_index=next_index,
        )
        self.repository.save_failover_event(
            agent.id,
            "FAILOVER",
            from_provider=from_provider,
            from_model=from_model,
            to_provider=route.provider,
            to_model=route.model,
            message=error_message[:1000],
        )
        self._apply_openclaw_route(agent.id, route.provider, route.model, route.LLM_BASE_URL)
        return self.active_route(agent)

    def maybe_restore_primary(self, agent: AgentSettings) -> bool:
        if not self.enabled_for(agent):
            return False
        state = self.repository.get_agent_failover_state(agent.id)
        if not state or not state.using_fallback:
            return False
        last = state.last_retest_at
        interval = max(60, agent.api_failover.retest_interval_seconds)
        if last and (datetime.now(UTC) - (last if last.tzinfo else last.replace(tzinfo=UTC))).total_seconds() < interval:
            return False
        if not self._probe_primary(agent, state):
            self.repository.upsert_agent_failover_state(
                agent.id,
                active_provider=state.active_provider,
                active_model=state.active_model,
                primary_provider=agent.provider,
                primary_model=agent.model,
                using_fallback=True,
                primary_available=False,
                fallback_index=state.fallback_index,
                last_retest_at=datetime.now(UTC),
            )
            return False
        self.repository.upsert_agent_failover_state(
            agent.id,
            active_provider=agent.provider,
            active_model=agent.model,
            primary_provider=agent.provider,
            primary_model=agent.model,
            using_fallback=False,
            primary_available=True,
            fallback_index=-1,
        )
        self.repository.save_failover_event(
            agent.id,
            "RESTORE_PRIMARY",
            from_provider=state.active_provider,
            from_model=state.active_model,
            to_provider=agent.provider,
            to_model=agent.model,
            message="Primary provider healthy again",
        )
        self._apply_openclaw_route(agent.id, agent.provider, agent.model, agent.llm.LLM_BASE_URL)
        return True

    def _probe_primary(self, agent: AgentSettings, current_state=None) -> bool:
        key_name = agent.llm.LLM_API_KEY
        if key_name and not os.getenv(key_name):
            return False
        binary = os.getenv("OPENCLAW_BIN", "openclaw")
        self._apply_openclaw_route(agent.id, agent.provider, agent.model, agent.llm.LLM_BASE_URL)
        try:
            completed = subprocess.run(
                [binary, "agent", "--agent", agent.id, "--session-id", f"{agent.id}-failover-probe", "--message", "Return exactly OK.", "--timeout", "60"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=75,
                check=False,
            )
            return completed.returncode == 0 and "OK" in (completed.stdout or "")
        except Exception:
            return False
        finally:
            if current_state and getattr(current_state, "using_fallback", 0):
                base_url = ""
                for route in agent.api_failover.fallback_chain:
                    if route.provider == current_state.active_provider and route.model == current_state.active_model:
                        base_url = route.LLM_BASE_URL
                        break
                self._apply_openclaw_route(
                    agent.id,
                    current_state.active_provider,
                    current_state.active_model,
                    base_url,
                )

    def _apply_openclaw_route(self, agent_id: str, provider: str, model: str, base_url: str) -> None:
        binary = os.getenv("OPENCLAW_BIN", "openclaw")
        openclaw_model = model if "/" in model else f"{provider}/{model}"
        _ROUTE_CMD_TIMEOUT = 30
        try:
            completed = subprocess.run(
                [binary, "models", "--agent", agent_id, "set", openclaw_model],
                capture_output=True,
                text=True,
                check=False,
                timeout=_ROUTE_CMD_TIMEOUT,
            )
            needs_add = completed.returncode != 0
        except Exception:
            needs_add = True
        if needs_add:
            try:
                subprocess.run(
                    [binary, "agents", "add", agent_id, "--model", openclaw_model],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=_ROUTE_CMD_TIMEOUT,
                )
            except Exception:
                logger.warning("failed to register openclaw route for {} → {}/{}; will retry next cycle", agent_id, provider, model)
        if base_url:
            self._sync_provider_base_url(provider, model, base_url)
        logger.info("failover route for {} uses provider {} model {}", agent_id, provider, model)

    @staticmethod
    def _sync_provider_base_url(provider: str, model: str, base_url: str) -> None:
        config_path = Path.home() / ".openclaw" / "openclaw.json"
        if config_path.exists():
            try:
                payload = json.loads(config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("unable to sync OpenClaw base URL for {}; config JSON is invalid", provider)
                return
        else:
            payload = {}
        models = payload.setdefault("models", {})
        models["mode"] = "merge"
        providers = models.setdefault("providers", {})
        providers[provider] = {
            "baseUrl": base_url,
            "api": "openai-completions",
            "models": [{"id": model, "name": model}],
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
