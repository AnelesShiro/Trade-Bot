from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta, timezone
from json import JSONDecodeError

from src.cloud.git_sync import sync_dashboard_snapshot
from src.cloud.snapshot_exporter import write_dashboard_snapshot
from src.agents.reflection import reflect_on_day, reflect_on_trade
from src.agents.api_failover import ApiFailoverManager
from src.agents.base_agent import AgentRunResult, OpenClawAgent
from src.agents.memory import AgentMemory
from src.agents.shared_learning import IDENTITY_BLOCK, SHARED_LESSON_DISCLAIMER, SharedLearningManager
from src.competition.api_cost_audit import prompt_audit_context, prompt_component_breakdown
from src.competition.checkpoint import build_checkpoint_payload, restore_from_checkpoint
from src.competition.config_manager import ConfigManager
from src.competition.evaluation import calculate_leaderboard
from src.competition.workload import WorkloadTracker
from src.config import Settings, load_rulebook, safe_canary, safe_features
from src.logger import logger
from src.schemas import Action, AgentSignal, MarketState, ValidationResult
from src.market.data_feed import MarketDataFeed
from src.storage.models import build_session_factory, create_schema
from src.storage.repository import ArenaRepository
from src.storage.vector_store import LocalVectorStore
from src.tools.backtest_pattern import backtest_pattern
from src.tools.get_market_state import get_market_state
from src.tools.retrieve_similar_trades import retrieve_similar_trades
from src.tools.toolbox import ALLOWED_TOOLS, execute_local_tool
from src.trading.execution import PaperExecutionEngine
from src.trading.paper_account import PaperAccount
from src.trading.position_manager import PositionManager
from src.trading.risk_automation import RiskAutomationEngine
from src.utils.costs import estimate_cost_usd
from src.validation.rule_engine import RuleEngine
from src.validation.signal_logger import signal_audit_metadata
from src.validation.signal_validator import validate_signal
from src.operations.preflight import has_critical_failures, run_preflight
from src.operations.update_manager import LiveUpdateManager


MAX_OPENCLAW_MESSAGE_CHARS = 24000
MAX_SIGNAL_REPAIR_ATTEMPTS = int(os.getenv("ARENA_SIGNAL_REPAIR_ATTEMPTS", "5"))
ORIGINAL_OPENCLAW_RUN = OpenClawAgent.run


class CompetitionRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        create_schema(settings.database_url)
        self.repository = ArenaRepository(build_session_factory(settings.database_url))
        self.config_manager = ConfigManager(self.repository)
        self.project_root = settings.resolve_path(settings.paths.outputs_dir).parent
        self.update_manager = LiveUpdateManager(settings, self.repository, project_root=self.project_root)
        self.update_manager.ensure_storage()
        self._apply_settings(settings)
        self._cycle_count = 0
        self._restart_requested = False

    def _apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.repository.upsert_agents(settings.agents)
        self.memory = AgentMemory(
            self.repository,
            LocalVectorStore(settings.resolve_path(settings.paths.outputs_dir).parent / "data" / "vectors"),
        )
        self.shared_learning = SharedLearningManager(self.repository, settings)
        self.shared_learning.ensure_storage()
        self.position_manager = PositionManager(
            self.repository,
            taker_fee_rate=settings.execution.taker_fee_rate,
            slippage_bps=settings.execution.slippage_bps,
            active_agent_ids={agent.id for agent in settings.agents},
        )
        self.position_manager.set_version_context(
            self.config_manager.config_version_id,
            self.config_manager.config_hash,
            self.config_manager.code_version,
        )
        self.execution = PaperExecutionEngine(self.position_manager)
        self.risk_engine = RiskAutomationEngine(settings, self.repository, self.position_manager, self.execution)
        self.failover_manager = ApiFailoverManager(settings, self.repository)
        self.rule_engine = RuleEngine(settings.risk, settings.accounts.initial_equity)
        self.rulebook = load_rulebook(settings)
        self.system_prompt = settings.resolve_path("prompts/system_prompt.md").read_text(encoding="utf-8")
        for agent in settings.agents:
            logger.info(
                "active locked LLM agent={} provider={} model={} fallback_allowed={}",
                agent.id,
                agent.provider,
                agent.model,
                agent.llm.LLM_ALLOW_FALLBACK,
            )
        if not hasattr(self, "_last_cloud_push_at"):
            self._last_cloud_push_at: float | None = None
        if not hasattr(self, "_prompt_audit_context"):
            self._prompt_audit_context: dict[str, dict[str, int]] = {}

    def run_once(self) -> None:
        cycle_number = self._cycle_count + 1
        cycle_started_at = datetime.now(UTC)
        self._active_cycle_started_at = cycle_started_at
        self._mark_runner_state("RUNNING", "FETCHING_DATA", cycle_number, started_at=cycle_started_at, message="Fetching market data")
        self.repository.ensure_competition_started("run_once")
        self._reload_runtime_config()
        self._ensure_not_killed()
        workload = WorkloadTracker()
        workload.local_function("market_data", "get_market_state")
        market_state = get_market_state(self.settings)
        snapshot_id = self.repository.save_market_snapshot(market_state)
        logger.info("frozen market snapshot {} at {} price {}", snapshot_id, market_state.timestamp, market_state.current_price)
        self._mark_runner_state("RUNNING", "MANAGING_POSITIONS", cycle_number, started_at=cycle_started_at, message="Updating local risk automation and stops")
        workload.database_query("position_management", details="load open positions for stop/target checks")
        workload.local_function("risk_management", "update_stops_and_targets")
        if self.risk_engine.enabled:
            try:
                self.risk_engine.run_market_tick(
                    market_state,
                    rsi_14=market_state.indicators.rsi_14,
                    atr_14=market_state.indicators.atr_14,
                )
            except Exception as error:
                logger.exception("risk automation pre-cycle tick failed without stopping trading: {}", error)
        for trade in self.position_manager.update_stops_and_targets(market_state.current_price):
            reflect_on_trade(self.memory, trade)
            workload.reflection(trade.agent_id)
        for agent in self.settings.agents:
            self._run_agent_round(agent_id=agent.id, market_state=market_state, workload=workload)
        self._mark_runner_state("RUNNING", "POST_PROCESSING", cycle_number, started_at=cycle_started_at, message="Persisting metrics and lessons")
        workload.local_function("analytics", "persist_daily_metrics")
        self._persist_daily_metrics(market_state, workload)
        workload.local_function("learning", "promote_lessons")
        promotion_result = self.shared_learning.promote_lessons()
        workload.lesson_promotion(int(promotion_result.get("promoted", 0)))
        workload.local_function("analytics", "analyze_diversity")
        self.shared_learning.analyze_diversity()
        self._mark_runner_state("RUNNING", "WRITING_OUTPUTS", cycle_number, started_at=cycle_started_at, message="Writing outputs and benchmark")
        workload.local_function("outputs", "write_outputs")
        self._write_outputs(market_state)
        workload.local_function("benchmark", "buy_and_hold_btc")
        self._save_benchmark(market_state)
        self._mark_runner_state("RUNNING", "CHECKPOINTING", cycle_number, started_at=cycle_started_at, message="Saving checkpoint")
        self._save_checkpoint(market_state, status="COMPLETED")
        cycle, components = workload.finalize()
        self.repository.save_workload_cycle(cycle, components)
        self._cycle_count += 1
        completed_at = datetime.now(UTC)
        self._mark_runner_state(
            "RUNNING",
            "WAITING",
            cycle_number,
            started_at=cycle_started_at,
            completed_at=completed_at,
            next_cycle_at=completed_at + timedelta(seconds=self.settings.competition.poll_interval_seconds),
            message="Cycle completed; waiting for next scheduled cycle",
            payload={"last_cycle_duration_seconds": cycle.get("payload", {}).get("total_wall_time_seconds")},
        )
        self._cloud_update_after_cycle()
        self._process_cycle_boundary_updates()

    def run_live(self, resume: bool = False) -> None:
        if self.settings.safety.require_preflight_for_live:
            self._wait_for_live_preflight()
        if resume:
            self._cycle_count = restore_from_checkpoint(
                self.repository,
                self.repository.latest_checkpoint(),
                self.settings.safety.downtime_threshold_seconds,
            )
            file_checkpoint = self.update_manager.latest_checkpoint_file()
            if file_checkpoint:
                file_cycle = int(file_checkpoint.get("cycle_number") or 0)
                self._cycle_count = max(self._cycle_count, file_cycle)
                self.repository.save_health_check(
                    "resume",
                    "PASS",
                    False,
                    f"Loaded filesystem checkpoint cycle {file_cycle}; SQLite remains canonical",
                )
        official_start = self.repository.ensure_competition_started("run_live")
        if official_start.tzinfo is None:
            official_start = official_start.replace(tzinfo=UTC)
        else:
            official_start = official_start.astimezone(UTC)
        logger.info("starting live competition loop from official start {}", official_start)
        ends_at = official_start.timestamp() + (self.settings.competition.duration_days * 86400)
        while datetime.now(UTC).timestamp() < ends_at:
            try:
                self._reload_runtime_config()
                self.run_once()
                if self._restart_requested:
                    logger.info("graceful restart requested; exiting live loop after completed cycle")
                    return
            except Exception as error:
                logger.exception("live loop failed: {}", error)
                self._mark_runner_state(
                    "ERROR",
                    "ERROR",
                    self._cycle_count + 1,
                    started_at=getattr(self, "_active_cycle_started_at", None),
                    message=str(error)[:1000],
                )
            self._sleep_with_position_monitor(self.settings.competition.poll_interval_seconds)
            if self._restart_requested:
                logger.info("graceful restart requested during wait; exiting live loop")
                return
        market_state = get_market_state(self.settings)
        self._persist_daily_metrics(market_state)
        self._write_outputs(market_state)
        self._save_checkpoint(market_state, status="COMPLETED")
        self._cloud_update_after_cycle()

    def _wait_for_live_preflight(self) -> None:
        while True:
            results = run_preflight(self.settings)
            for result in results:
                self.repository.save_health_check(result.component, result.status, result.critical, result.message)
            if not has_critical_failures(results):
                return
            failed = [result.component for result in results if not result.passed and result.critical]
            if failed != ["market_data_feed"]:
                raise RuntimeError(f"preflight-check failed; live execution blocked: {', '.join(failed)}")
            retry_seconds = min(60, max(5, self.settings.competition.poll_interval_seconds))
            logger.warning("market data preflight failed; retrying live startup in {}s", retry_seconds)
            time.sleep(retry_seconds)

    def _process_cycle_boundary_updates(self) -> None:
        pending = self.update_manager.pending_updates()
        if not pending:
            return
        validation = self.update_manager.validate_update(run_smoke=True)
        if not validation.passed:
            for entry in pending:
                self.update_manager.mark_update(str(entry["id"]), "FAILED", {"validation": validation.checks})
                self.update_manager.audit("VALIDATION_FAILED", str(entry["type"]), "Update validation failed; trading continues", {"id": entry["id"], "checks": validation.checks})
            return
        for entry in pending:
            update_id = str(entry["id"])
            update_type = str(entry["type"])
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
            try:
                if update_type == "CONFIG_RELOAD":
                    updated = self.config_manager.reload(source=f"update:{update_id}")
                    self._apply_settings(updated)
                    self.update_manager = LiveUpdateManager(updated, self.repository, project_root=self.project_root)
                    self.update_manager.ensure_storage()
                    self.update_manager.mark_update(update_id, "APPLIED", {"config_hash": self.config_manager.config_hash})
                elif update_type in {"PROMPT_UPDATE", "RULEBOOK_UPDATE"}:
                    self.update_manager.backup_current_state(update_type.lower())
                    result = self.update_manager.apply_file_update(update_type, payload)
                    if update_type == "PROMPT_UPDATE":
                        self.system_prompt = self.settings.resolve_path("prompts/system_prompt.md").read_text(encoding="utf-8")
                    else:
                        self.rulebook = load_rulebook(self.settings)
                    self.update_manager.mark_update(update_id, "APPLIED", result)
                elif update_type == "CODE_RESTART":
                    backup = self.update_manager.backup_current_state("code-restart")
                    self.update_manager.request_restart("code-restart", update_id)
                    self.update_manager.mark_update(update_id, "APPLIED", {"backup": str(backup)})
                    self._restart_requested = True
                elif update_type == "ROLLBACK":
                    self.update_manager.backup_current_state("pre-rollback")
                    result = self.update_manager.rollback_from_backup(payload.get("backup_path"))
                    updated = self.config_manager.reload(source=f"rollback:{update_id}")
                    self._apply_settings(updated)
                    self.rulebook = load_rulebook(self.settings)
                    self.system_prompt = self.settings.resolve_path("prompts/system_prompt.md").read_text(encoding="utf-8")
                    self.update_manager.request_restart("rollback", update_id)
                    self.update_manager.mark_update(update_id, "APPLIED", result)
                    self._restart_requested = True
                else:
                    self.update_manager.mark_update(update_id, "FAILED", {"error": f"unknown update type {update_type}"})
            except Exception as error:
                self.update_manager.mark_update(update_id, "FAILED", {"error": str(error)})
                self.update_manager.audit("FAILED", update_type, str(error), {"id": update_id})

    def _sleep_with_position_monitor(self, total_seconds: int | float) -> None:
        remaining = max(0.0, float(total_seconds))
        interval = max(1.0, float(self.settings.safety.position_monitor_interval_seconds))
        if not (self.settings.safety.position_monitor_enabled and safe_features(self.settings).event_driven_tp_sl):
            time.sleep(remaining)
            return
        while remaining > 0:
            nap = min(interval, remaining)
            time.sleep(nap)
            remaining -= nap
            if remaining <= 0:
                break
            try:
                self._monitor_positions_once()
            except Exception as error:
                logger.exception("position monitor failed without stopping live loop: {}", error)
                self.repository.save_health_check("position_monitor", "FAIL", False, str(error)[:1000])

    def _monitor_positions_once(self) -> None:
        self._ensure_not_killed()
        if not self.repository.open_positions():
            return
        feed = MarketDataFeed(self.settings.market)
        current_price = feed.fetch_ticker_price(self.settings.competition.symbol)
        market_state = MarketState(
            symbol=self.settings.competition.display_symbol,
            exchange=self.settings.market.exchange,
            current_price=current_price,
            timeframe="ticker",
        )
        if self.risk_engine.enabled:
            try:
                self.risk_engine.run_market_tick(
                    market_state,
                    rsi_14=None,
                    atr_14=None,
                )
            except Exception as error:
                logger.exception("risk automation monitor tick failed: {}", error)
        exit_trades = self.position_manager.update_stops_and_targets(current_price)
        if not exit_trades:
            return
        snapshot_id = self.repository.save_market_snapshot(market_state)
        logger.info(
            "position monitor closed/reduced {} position legs at price {} snapshot {}",
            len(exit_trades),
            current_price,
            snapshot_id,
        )
        for trade in exit_trades:
            reflect_on_trade(self.memory, trade)
        self._persist_daily_metrics(market_state)
        self._write_outputs(market_state)
        self._save_checkpoint(market_state, status="MONITOR", cycle_number=self._current_completed_cycle_number())
        self.repository.save_health_check(
            "position_monitor",
            "PASS",
            False,
            f"Processed {len(exit_trades)} automatic TP/SL exits at {current_price}",
        )
        self._cloud_update_after_cycle()

    def _run_agent_round(self, agent_id: str, market_state: MarketState, workload: WorkloadTracker | None = None) -> None:
        phase = f"CALLING_{agent_id.replace('crypto-', '').upper()}"
        self._mark_runner_state(
            "RUNNING",
            phase,
            self._cycle_count + 1,
            started_at=getattr(self, "_active_cycle_started_at", None),
            message=f"Calling {agent_id} and validating its signal",
        )
        agent_settings = next(agent for agent in self.settings.agents if agent.id == agent_id)
        self.failover_manager.maybe_restore_primary(agent_settings)
        active_route = self.failover_manager.active_route(agent_settings)
        effective_agent_settings = self.failover_manager.settings_for_route(agent_settings, active_route)
        if self.risk_engine.enabled and self.risk_engine.blocks_new_entries(agent_id):
            self.repository.save_health_check("cooldown", "PASS", False, f"{agent_id} entry cooldown active; skipped LLM cycle")
            return
        if workload:
            workload.local_function("accounting", "account_summary", agent_id=agent_id)
            workload.database_query("accounting", agent_id=agent_id)
        account = PaperAccount(agent_id, self.settings.accounts.initial_equity, self.repository)
        summary = account.summary(market_state.current_price)
        if workload:
            workload.memory_retrieval(agent_id=agent_id)
        private_lessons = self.memory.retrieve_lessons(agent_id, f"{market_state.regime} BTC")
        if workload:
            workload.memory_retrieval(agent_id=agent_id, memory_type="shared_learning")
        retrieved_lessons = self.shared_learning.retrieve_for_prompt(
            agent_id,
            f"{market_state.regime} BTC {market_state.indicators.model_dump()}",
            private_lessons,
        )
        if workload:
            workload.local_function("analytics", "retrieve_similar_trades", agent_id=agent_id)
            workload.database_query("analytics", agent_id=agent_id)
        similar = retrieve_similar_trades(self.repository, agent_id)
        profile = self.shared_learning.profile(agent_id)
        if workload:
            workload.local_function("analytics", "backtest_pattern", agent_id=agent_id)
        tool_context = {
            "market_state": market_state.compact(),
            "account_summary": summary.model_dump(mode="json"),
            "similar_trades": similar,
            "backtest_diagnostic": backtest_pattern(_candles_to_frame(market_state)).copy(),
            "strategy_profile": profile.model_dump(),
            "private_lessons": retrieved_lessons.private_lessons,
            "shared_lessons": retrieved_lessons.shared_lessons,
            "shared_learning": {
                "shared_ratio_applied": retrieved_lessons.shared_ratio_applied,
                "convergence_warning": retrieved_lessons.convergence_warning,
                "shared_lesson_ids": retrieved_lessons.shared_lesson_ids,
                "shared_lessons_are_advisory_only": True,
            },
            "feature_flags": self._feature_flags_for_agent(agent_id),
            "version_context": {
                "config_version_id": self.config_manager.config_version_id,
                "config_hash": self.config_manager.config_hash,
                "code_version": self.config_manager.code_version,
            },
        }
        if workload:
            workload.database_query("logging", agent_id=agent_id)
        self.repository.save_tool_call(agent_id, "compose_context", {"agent_id": agent_id}, tool_context)
        self._prompt_audit_context[agent_id] = prompt_audit_context(tool_context)
        if workload:
            workload.local_function("prompt_construction", "compose_prompt", agent_id=agent_id)
        prompt = self._compose_prompt(agent_id, tool_context)
        self._record_prompt_version(prompt)
        if workload:
            workload.database_query("logging", agent_id=agent_id)
        prompt_id = self.repository.save_prompt(agent_id, prompt)
        try:
            signal, validation, raw, signal_record_id = self._run_until_valid_signal(
                agent_settings=effective_agent_settings,
                agent_id=agent_id,
                prompt=prompt,
                prompt_id=prompt_id,
                market_state=market_state,
                summary=summary,
                workload=workload,
            )
        except Exception as error:
            raw = f"AGENT_RUNTIME_ERROR: {error}"
            validation = ValidationResult(accepted=False, reasons=[raw])
            logger.error("agent {} failed without stopping cycle: {}", agent_id, error)
            self.repository.save_health_check("agent_call", "FAIL", False, f"{agent_id}: {error}"[:1000])
            signal_record_id = self._save_signal_audit(
                agent_settings=agent_settings,
                agent_id=agent_id,
                signal=None,
                validation=validation,
                raw=raw,
                market_state=market_state,
                active_prompt=prompt,
                input_tokens=0,
                output_tokens=0,
                estimated_cost=0.0,
                latency_ms=None,
            )
            if workload:
                workload.database_query("logging", agent_id=agent_id)
                workload.local_function("outputs", "append_signal_output", agent_id=agent_id)
            self._append_signal_output(agent_id, raw, False, validation.reasons)
            self._record_signal_execution(
                signal_record_id,
                {
                    "executed": False,
                    "reason": "agent_runtime_error",
                    "decision": "AGENT_RUNTIME_ERROR",
                    "action": "NONE",
                },
            )
            return
        if self._is_warmup_cycle():
            logger.info("warm-up mode active; skipping paper execution for {}", agent_id)
            self.repository.save_health_check("warmup_mode", "PASS", False, f"Skipped execution for {agent_id}")
            self._record_signal_execution(signal_record_id, {"executed": False, "reason": "warmup_mode"})
            return
        if signal and validation.accepted and signal.action == Action.PLACE_TRIGGER:
            try:
                order_id = self.risk_engine.handle_place_trigger(signal, signal_record_id)
                self._record_signal_execution(
                    signal_record_id,
                    {"executed": bool(order_id), "pending_order_id": order_id, "action": signal.action.value},
                )
            except Exception as error:
                logger.exception("PLACE_TRIGGER failed without stopping cycle: {}", error)
                self._record_signal_execution(signal_record_id, {"executed": False, "reason": str(error)})
            return
        if signal and validation.accepted and signal.decision.value in {"PAPER_TRADE", "POSITION_UPDATE"}:
            if workload:
                workload.local_function("paper_execution", "execute_signal", agent_id=agent_id)
                workload.database_query("paper_execution", agent_id=agent_id)
            position_id = self.execution.execute(signal, market_state.current_price)
            if position_id and signal.action == Action.OPEN:
                try:
                    self.risk_engine.attach_position_risk(position_id, signal)
                except Exception as error:
                    logger.warning("attach position risk failed for {}: {}", position_id, error)
            self._record_signal_execution(
                signal_record_id,
                {
                    "executed": bool(position_id),
                    "position_id": position_id,
                    "decision": signal.decision.value,
                    "action": signal.action.value,
                },
            )
            if position_id and signal.action in {Action.REDUCE, Action.CUT, Action.CLOSE}:
                if workload:
                    workload.database_query("reflection", agent_id=agent_id)
                trade = self.repository.latest_trade_for_position(position_id)
                if trade and trade.exit_price is not None:
                    reflect_on_trade(self.memory, trade)
                    if workload:
                        workload.reflection(agent_id)
        else:
            self._record_signal_execution(
                signal_record_id,
                {
                    "executed": False,
                    "reason": "non_trade_decision" if validation.accepted else "validation_rejected",
                    "decision": signal.decision.value if signal else "PARSE_ERROR",
                    "action": signal.action.value if signal else "NONE",
                },
            )
        try:
            account = PaperAccount(agent_id, self.settings.accounts.initial_equity, self.repository)
            summary = account.summary(market_state.current_price)
            self.risk_engine.evaluate_agent_cooldowns(agent_id, equity=summary.equity, daily_pnl=summary.daily_pnl)
        except Exception as error:
            logger.warning("cooldown evaluation failed for {}: {}", agent_id, error)

    def _run_until_valid_signal(
        self,
        agent_settings,
        agent_id: str,
        prompt: str,
        prompt_id: int,
        market_state: MarketState,
        summary,
        workload: WorkloadTracker | None,
    ):
        agent = OpenClawAgent(agent_settings)
        active_prompt = prompt
        active_prompt_id = prompt_id
        call_started = time.perf_counter()
        raw = self._run_agent_with_tools(agent, agent_id, active_prompt, active_prompt_id, market_state, workload, request_type="signal")
        latency_ms = int((time.perf_counter() - call_started) * 1000)
        for attempt in range(MAX_SIGNAL_REPAIR_ATTEMPTS + 1):
            input_tokens, output_tokens, estimated_cost = estimate_cost_usd(agent_settings.model, active_prompt, raw)
            if workload:
                workload.agent_tokens(agent_id, input_tokens, output_tokens, estimated_cost)
                workload.database_query("logging", agent_id=agent_id)
            self.repository.save_response(
                agent_id,
                raw,
                prompt_id=active_prompt_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost,
            )
            signal, validation = self._validate_raw_signal(agent_id, raw, summary, workload)
            if workload:
                workload.database_query("logging", agent_id=agent_id)
            signal_record_id = self._save_signal_audit(
                agent_settings=agent_settings,
                agent_id=agent_id,
                signal=signal,
                validation=validation,
                raw=raw,
                market_state=market_state,
                active_prompt=active_prompt,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=estimated_cost,
                latency_ms=latency_ms,
            )
            if workload:
                workload.local_function("outputs", "append_signal_output", agent_id=agent_id)
            self._append_signal_output(agent_id, raw, validation.accepted, validation.reasons)
            if validation.accepted:
                if attempt:
                    self.repository.save_health_check(
                        "signal_repair",
                        "PASS",
                        False,
                        f"{agent_id} produced accepted signal after {attempt} repair attempt(s)",
                    )
                return signal, validation, raw, signal_record_id
            if attempt >= MAX_SIGNAL_REPAIR_ATTEMPTS:
                self.repository.save_health_check(
                    "signal_repair",
                    "FAIL",
                    False,
                    f"{agent_id} still rejected after {MAX_SIGNAL_REPAIR_ATTEMPTS} repair attempt(s): {'; '.join(validation.reasons)[:500]}",
                )
                return signal, validation, raw, signal_record_id
            active_prompt = self._compose_repair_prompt(agent_id, raw, validation.reasons, attempt + 1)
            active_prompt_id = self.repository.save_prompt(agent_id, active_prompt)
            if workload:
                workload.local_function("prompt_construction", "compose_repair_prompt", agent_id=agent_id)
                workload.database_query("logging", agent_id=agent_id)
            call_started = time.perf_counter()
            raw = self._run_agent_with_tools(agent, agent_id, active_prompt, active_prompt_id, market_state, workload, request_type="signal_repair")
            latency_ms = int((time.perf_counter() - call_started) * 1000)

    def _save_signal_audit(
        self,
        *,
        agent_settings,
        agent_id: str,
        signal: AgentSignal | None,
        validation,
        raw: str,
        market_state: MarketState,
        active_prompt: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost: float,
        latency_ms: int,
    ) -> int | None:
        try:
            metadata = signal_audit_metadata(
                agent_name=agent_settings.name,
                model_name=agent_settings.model,
                cycle_number=self._cycle_count + 1,
                competition_time_pct=self._competition_time_pct(),
                market_regime=market_state.regime,
                btc_price=market_state.current_price,
                timeframe=market_state.timeframe,
                prompt_version=_sha256(active_prompt),
                rulebook_version=_sha256(self.rulebook),
                config_version=self.config_manager.config_hash,
                signal=signal,
                validation=validation,
                raw_response=raw,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                api_cost_usd=estimated_cost,
                latency_ms=latency_ms,
            )
            return self.repository.save_signal(agent_id, signal, validation, raw, metadata=metadata)
        except Exception as error:
            logger.warning("signal audit logging failed for {} without affecting trading: {}", agent_id, error)
            return None

    def _record_signal_execution(self, signal_record_id: int | None, result: dict[str, object]) -> None:
        if signal_record_id is None:
            return
        try:
            self.repository.update_signal_execution(signal_record_id, result)
        except Exception as error:
            logger.warning("signal execution audit update failed without affecting trading: {}", error)

    def _validate_raw_signal(self, agent_id: str, raw: str, summary, workload: WorkloadTracker | None):
        if workload:
            workload.local_function("validation", "prevalidate_signal", agent_id=agent_id)
        dca_count = 0
        signal_for_dca, _ = validate_signal(
            raw,
            self.rule_engine,
            current_equity=summary.equity,
            open_positions_count=len(summary.open_positions),
            current_total_risk=summary.open_risk,
            daily_pnl=summary.daily_pnl,
        )
        if signal_for_dca and signal_for_dca.position_id:
            if workload:
                workload.database_query("validation", agent_id=agent_id)
            existing = self.repository.get_position(signal_for_dca.position_id)
            dca_count = existing.dca_count if existing else 0
        if workload:
            workload.database_query("validation", agent_id=agent_id)
        latest_checkpoint = self.repository.latest_checkpoint()
        recent_stop = bool(
            signal_for_dca
            and signal_for_dca.action == Action.OPEN
            and self.repository.latest_stop_loss_same_direction(
                agent_id,
                signal_for_dca.direction.value,
                since=latest_checkpoint.created_at if latest_checkpoint else None,
            )
        )
        if workload:
            workload.local_function("validation", "validate_signal", agent_id=agent_id)
        return validate_signal(
            raw,
            self.rule_engine,
            current_equity=summary.equity,
            open_positions_count=len(summary.open_positions),
            current_total_risk=summary.open_risk,
            daily_pnl=summary.daily_pnl,
            dca_count_for_position=dca_count,
            recent_stop_loss_same_direction=recent_stop,
        )

    def _compose_repair_prompt(self, agent_id: str, rejected_raw: str, reasons: list[str], attempt: int) -> str:
        schema_hint = {
            "agent": agent_id,
            "decision": "NO_TRADE|WATCHLIST|PAPER_TRADE|POSITION_UPDATE",
            "action": "NONE|OPEN|ADD|DCA|REDUCE|CUT|CLOSE|HOLD|PLACE_TRIGGER",
            "symbol": "BTC",
            "direction": "NONE|LONG|SHORT",
            "execution_type": "NONE|MARKET|LIMIT|CONDITIONAL",
            "data_used": ["list", "of", "strings"],
            "risk_math": {
                "notional_exposure_usdt": "margin_used_usdt * leverage",
                "account_risk_usdt": "abs(entry - stop_loss) / entry * notional_exposure_usdt",
                "account_risk_percent": "account_risk_usdt / account_equity; use decimal fraction",
                "warning": "Do not multiply by leverage again after using notional_exposure_usdt.",
            },
            "allowed_fields_only": sorted(AgentSignal.model_fields),
        }
        no_trade_example = {
            "agent": agent_id,
            "decision": "NO_TRADE",
            "action": "NONE",
            "symbol": "BTC",
            "direction": "NONE",
            "execution_type": "NONE",
            "thesis": "No compliant setup after validation feedback.",
            "invalidation": "A compliant setup appears with valid risk/reward and complete data.",
            "counterargument": "Standing aside may miss a move, but avoids invalid execution.",
            "data_used": ["validation_feedback", "previous_context"],
        }
        prompt = "\n\n".join(
            [
                f"Your previous response for {agent_id} was REJECTED by the paper-trading validator.",
                f"Repair attempt {attempt} of {MAX_SIGNAL_REPAIR_ATTEMPTS}.",
                "Return exactly one JSON object only. No markdown, no prose.",
                "Fix every validation issue. Do not include extra fields. data_used must be a JSON list, not a string.",
                "If you cannot produce a compliant PAPER_TRADE or POSITION_UPDATE, return a compliant NO_TRADE JSON instead.",
                "VALIDATION REASONS:\n" + json.dumps(reasons, separators=(",", ":"), default=str),
                "STRICT SCHEMA HINT:\n" + json.dumps(schema_hint, separators=(",", ":"), default=str),
                "SAFE ACCEPTED FALLBACK EXAMPLE:\n" + json.dumps(no_trade_example, separators=(",", ":")),
                "REJECTED RESPONSE TO FIX:\n" + _truncate_text(rejected_raw, 4500),
            ]
        )
        return prompt[:MAX_OPENCLAW_MESSAGE_CHARS]

    def _run_agent_with_tools(
        self,
        agent: OpenClawAgent,
        agent_id: str,
        prompt: str,
        prompt_id: int,
        market_state: MarketState,
        workload: WorkloadTracker | None = None,
        request_type: str = "signal",
    ) -> str:
        started = time.perf_counter()
        try:
            call = self._call_agent_result(agent, prompt)
        except Exception as error:
            self._save_api_request_audit(
                agent=agent,
                agent_id=agent_id,
                request_type=request_type,
                prompt=prompt,
                response="",
                latency_ms=int((time.perf_counter() - started) * 1000),
                retry_count=max(0, int(self.settings.api.max_retries) - 1),
                success=False,
                local_tool_invocation_count=0,
                error_message=str(error)[:2000],
                actual_model_name=agent.settings.model,
            )
            raise
        raw = call.output
        if workload:
            workload.agent_latency(agent_id, time.perf_counter() - started)
        self._save_api_request_audit(
            agent=agent,
            agent_id=agent_id,
            request_type=request_type,
            prompt=prompt,
            response=raw,
            latency_ms=call.latency_ms,
            retry_count=call.retry_count,
            success=True,
            local_tool_invocation_count=0,
            actual_model_name=call.actual_model,
            configured_model_name=call.configured_model,
        )
        for step in range(2):
            request = _parse_tool_request(raw)
            if not request:
                return raw
            if workload:
                workload.agent_tool_requests(agent_id, len(request))
                workload.database_query("logging", agent_id=agent_id)
            self.repository.save_response(agent_id, raw, prompt_id=prompt_id)
            results = []
            for item in request:
                tool_name = str(item.get("tool", ""))
                arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                try:
                    result = execute_local_tool(
                        tool_name,
                        arguments,
                        self.settings,
                        self.repository,
                        market_state,
                        agent_id,
                    )
                except Exception as error:
                    result = {"error": str(error)}
                if workload:
                    workload.local_tool(tool_name, agent_id=agent_id, step=step)
                    workload.database_query("logging", agent_id=agent_id)
                self.repository.save_tool_call(agent_id, tool_name, arguments, result)
                results.append({"tool": tool_name, "arguments": arguments, "result": result})
            followup = (
                prompt
                + "\n\nLOCAL TOOL RESULTS:\n"
                + json.dumps(results, indent=2, default=str)
                + "\n\nReturn the final strict AgentSignal JSON now. Do not request more tools unless essential."
            )
            followup_prompt_id = self.repository.save_prompt(agent_id, followup)
            if workload:
                workload.database_query("logging", agent_id=agent_id)
            started = time.perf_counter()
            try:
                call = self._call_agent_result(agent, followup)
            except Exception as error:
                self._save_api_request_audit(
                    agent=agent,
                    agent_id=agent_id,
                    request_type="tool_followup",
                    prompt=followup,
                    response="",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    retry_count=max(0, int(self.settings.api.max_retries) - 1),
                    success=False,
                    local_tool_invocation_count=len(request),
                    error_message=str(error)[:2000],
                    actual_model_name=agent.settings.model,
                )
                raise
            raw = call.output
            if workload:
                workload.agent_latency(agent_id, time.perf_counter() - started)
                workload.database_query("logging", agent_id=agent_id)
            self._save_api_request_audit(
                agent=agent,
                agent_id=agent_id,
                request_type="tool_followup",
                prompt=followup,
                response=raw,
                latency_ms=call.latency_ms,
                retry_count=call.retry_count,
                success=True,
                local_tool_invocation_count=len(request),
                actual_model_name=call.actual_model,
                configured_model_name=call.configured_model,
            )
            self.repository.save_response(agent_id, raw, prompt_id=followup_prompt_id)
        return raw

    def _compose_prompt(self, agent_id: str, context: dict) -> str:
        context = _compact_prompt_context(context)
        schema_hint = {
            "agent": agent_id,
            "decision": "NO_TRADE|WATCHLIST|PAPER_TRADE|POSITION_UPDATE",
            "action": "NONE|OPEN|ADD|DCA|REDUCE|CUT|CLOSE|HOLD|PLACE_TRIGGER",
            "symbol": "BTC",
            "direction": "NONE|LONG|SHORT",
            "execution_type": "NONE|MARKET|LIMIT|CONDITIONAL",
            "risk_math": {
                "notional_exposure_usdt": "margin_used_usdt * leverage",
                "account_risk_usdt": "abs(entry - stop_loss) / entry * notional_exposure_usdt",
                "account_risk_percent": "account_risk_usdt / account_equity; use decimal fraction",
                "example": "entry 77000, stop 76500, notional 5000 => account_risk_usdt 32.47 and account_risk_percent 0.003247 on 10000 equity",
                "warning": "Do not multiply by leverage again after using notional_exposure_usdt.",
            },
            "required_for_trades": [
                "entry",
                "leverage",
                "margin_used_usdt",
                "stop_loss",
                "take_profit_1",
                "take_profit_2",
                "account_risk_usdt",
                "thesis",
                "invalidation",
                "counterargument",
                "data_used",
            ],
            "optional_tool_request_format": {
                "tool_requests": [
                    {
                        "tool": sorted(ALLOWED_TOOLS)[0],
                        "arguments": {},
                    }
                ]
            },
            "advanced_trade_management": {
                "consider_every_cycle": True,
                "PLACE_TRIGGER": "Prefer when entry needs future pullback, breakout, or RSI confirmation; include trigger_order and full nested execution_signal.",
                "position_risk": "Break-even is always enforced locally around +1R; on OPEN, consider time_exit and add trailing_stop for momentum or trend-continuation trades.",
                "cooldown": "If cooldown context is active, avoid new entries unless managing existing positions.",
                "failover": "Automatic and transparent; keep reasoning provider-neutral.",
            },
            "available_local_tools": sorted(ALLOWED_TOOLS),
            "feature_flags": self._feature_flags_for_agent(agent_id),
        }
        profile = self.shared_learning.profile(agent_id)
        shared_context = context.get("shared_learning", {})
        convergence_note = (
            "ANTI-CONVERGENCE MODE: action agreement is elevated. Weight private lessons more heavily and be stricter with shared lessons."
            if shared_context.get("convergence_warning")
            else "Diversity status: normal. Maintain your own strategy identity."
        )
        prompt = "\n\n".join(
            [
                self._system_prompt_for_agent(agent_id),
                "RULEBOOK:\n" + self.rulebook,
                "STRATEGY IDENTITY:\n" + profile.strategy_identity_statement() + "\n\n" + IDENTITY_BLOCK + "\n" + convergence_note,
                "PRIVATE LESSONS (primary memory, highest weight):\n" + json.dumps(context.get("private_lessons", []), separators=(",", ":"), default=str),
                "SHARED LESSONS (advisory, max 30% unless anti-convergence reduces it):\n"
                + SHARED_LESSON_DISCLAIMER
                + "\n"
                + json.dumps(context.get("shared_lessons", []), separators=(",", ":"), default=str),
                "STRICT JSON SCHEMA HINT:\n" + json.dumps(schema_hint, separators=(",", ":")),
                "CURRENT CONTEXT:\n" + json.dumps(context, separators=(",", ":"), default=str),
            ]
        )
        if len(prompt) <= MAX_OPENCLAW_MESSAGE_CHARS:
            return prompt
        minimal_context = _minimal_prompt_context(context)
        prompt = "\n\n".join(
            [
                self._system_prompt_for_agent(agent_id),
                "RULEBOOK:\n" + self.rulebook,
                "STRATEGY IDENTITY:\n" + profile.strategy_identity_statement() + "\n\n" + IDENTITY_BLOCK + "\n" + convergence_note,
                "STRICT JSON SCHEMA HINT:\n" + json.dumps(schema_hint, separators=(",", ":")),
                "CURRENT CONTEXT:\n" + json.dumps(minimal_context, separators=(",", ":"), default=str),
                "Context was compressed to fit the local OpenClaw CLI message limit. Use available_local_tools if more market detail is essential.",
            ]
        )
        return prompt[:MAX_OPENCLAW_MESSAGE_CHARS]

    def _record_prompt_version(self, prompt: str) -> None:
        self.repository.save_prompt_version(
            prompt_hash=_sha256(prompt),
            system_prompt_hash=_sha256(self.system_prompt),
            rulebook_hash=_sha256(self.rulebook),
            prompt_preview=prompt[:1000],
        )

    def _system_prompt_for_agent(self, agent_id: str) -> str:
        canary = safe_canary(self.settings)
        if not canary.enabled or agent_id not in set(canary.target_agents):
            return self.system_prompt
        versions = self.update_manager.deployment_state().get("active_versions_file", {})
        canary = versions.get("canary_prompts", {}) if isinstance(versions, dict) else {}
        prompt_info = canary.get(agent_id, {}) if isinstance(canary, dict) else {}
        prompt_path = prompt_info.get("path")
        if not prompt_path:
            return self.system_prompt
        path = self.settings.resolve_path(prompt_path)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return self.system_prompt
        return text if text.strip() else self.system_prompt

    def _reload_runtime_config(self) -> None:
        current = self.config_manager.process_pending_commands(self.settings)
        if self.settings.hot_reload.enabled and self.settings.hot_reload.auto_detect_changes:
            current = self.config_manager.reload_if_changed(current)
        if current is not self.settings:
            self._apply_settings(current)
            self.update_manager = LiveUpdateManager(current, self.repository, project_root=self.project_root)
            self.update_manager.ensure_storage()
            logger.info("active config {} code {}", self.config_manager.config_hash, self.config_manager.code_version)

    def _feature_flags_for_agent(self, agent_id: str) -> dict[str, bool]:
        flags = {name: self.settings.feature_enabled(name, agent_id) for name in self.settings.feature_flags}
        features = safe_features(self.settings)
        canary = safe_canary(self.settings)
        flags.update(features.model_dump())
        flags["canary_target"] = canary.enabled and agent_id in set(canary.target_agents)
        return flags

    def _cloud_update_after_cycle(self) -> None:
        if not (self.settings.cloud_dashboard.enabled and safe_features(self.settings).cloud_sync):
            return
        try:
            write_dashboard_snapshot(self.settings, self.repository)
            if not (self.settings.cloud_dashboard.git_auto_push and self.settings.cloud_dashboard.push_after_each_cycle):
                return
            now = time.time()
            min_interval = self.settings.cloud_dashboard.min_push_interval_seconds
            if self._last_cloud_push_at and now - self._last_cloud_push_at < min_interval:
                self.repository.save_health_check("cloud_git_sync", "PASS", False, "Skipped push; minimum interval not reached")
                return
            result = sync_dashboard_snapshot(self.settings, self.repository)
            if result.pushed:
                self._last_cloud_push_at = now
        except Exception as error:
            logger.exception("cloud dashboard update failed without stopping trading: {}", error)
            self.repository.save_health_check("cloud_dashboard", "FAIL", False, str(error)[:1000])

    def _call_agent(self, agent: OpenClawAgent, prompt: str) -> str:
        return self._call_agent_result(agent, prompt).output

    def _call_agent_result(self, agent: OpenClawAgent, prompt: str):
        if type(agent).run is not ORIGINAL_OPENCLAW_RUN:
            started = time.perf_counter()
            output = agent.run(prompt, timeout_seconds=self.settings.api.timeout_seconds)
            return AgentRunResult(
                output=output,
                retry_count=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                configured_model=agent.settings.model,
                actual_model=agent.settings.model,
            )
        try:
            return agent.run_with_metadata(
                prompt,
                timeout_seconds=self.settings.api.timeout_seconds,
                max_retries=self.settings.api.max_retries,
                backoff_initial_seconds=self.settings.api.backoff_initial_seconds,
                backoff_multiplier=self.settings.api.backoff_multiplier,
            )
        except RuntimeError as error:
            route = self.failover_manager.handle_failure(agent.settings, str(error))
            if route:
                fallback_agent = OpenClawAgent(self.failover_manager.settings_for_route(agent.settings, route))
                return fallback_agent.run_with_metadata(
                    prompt,
                    timeout_seconds=self.settings.api.timeout_seconds,
                    max_retries=1,
                    backoff_initial_seconds=self.settings.api.backoff_initial_seconds,
                    backoff_multiplier=self.settings.api.backoff_multiplier,
                )
            raise
        except TypeError as error:
            if "unexpected keyword" not in str(error):
                raise
            output = agent.run(prompt, timeout_seconds=self.settings.api.timeout_seconds)
            return AgentRunResult(
                output=output,
                retry_count=0,
                latency_ms=0,
                configured_model=agent.settings.model,
                actual_model=agent.settings.model,
            )

    def _save_api_request_audit(
        self,
        *,
        agent: OpenClawAgent,
        agent_id: str,
        request_type: str,
        prompt: str,
        response: str,
        latency_ms: int,
        retry_count: int,
        success: bool,
        local_tool_invocation_count: int,
        error_message: str | None = None,
        actual_model_name: str | None = None,
        configured_model_name: str | None = None,
    ) -> None:
        try:
            model_name = configured_model_name or agent.settings.model
            prompt_tokens, completion_tokens, token_cost = estimate_cost_usd(model_name, prompt, response)
            breakdown = self._cost_breakdown(prompt, response, token_cost)
            context = dict(self._prompt_audit_context.get(agent_id, {}))
            self.repository.save_api_request(
                {
                    "timestamp": datetime.now(UTC),
                    "cycle_number": self._cycle_count + 1,
                    "agent_name": agent_id,
                    "model_name": model_name,
                    "actual_model_name": actual_model_name or model_name,
                    "request_type": request_type,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "reasoning_tokens": 0,
                    "server_tool_calls": 0,
                    "server_tool_cost_usd": 0.0,
                    "token_cost_usd": token_cost,
                    "total_cost_usd": token_cost,
                    "latency_ms": latency_ms,
                    "retry_count": retry_count,
                    "prompt_characters": len(prompt),
                    "response_characters": len(response),
                    "prompt_hash": _sha256(prompt),
                    "response_hash": _sha256(response),
                    "prompt_version": _sha256(prompt),
                    "rulebook_version": _sha256(self.rulebook),
                    "config_version": self.config_manager.config_hash,
                    "success": success,
                    "error_message": error_message,
                    "local_tool_invocation_count": local_tool_invocation_count,
                    "cost_breakdown": breakdown,
                    **context,
                }
            )
        except Exception as error:
            logger.warning("api request audit logging failed for {} without affecting trading: {}", agent_id, error)

    def _cost_breakdown(self, prompt: str, response: str, total_cost: float) -> dict[str, float]:
        prompt_parts = prompt_component_breakdown(prompt)
        prompt_total = max(1, sum(prompt_parts.values()))
        prompt_cost = total_cost * (len(prompt) / max(1, len(prompt) + len(response)))
        response_cost = total_cost - prompt_cost
        breakdown = {f"{name}_cost_usd": prompt_cost * (chars / prompt_total) for name, chars in prompt_parts.items()}
        breakdown["response_tokens_cost_usd"] = response_cost
        breakdown["server_side_tools_cost_usd"] = 0.0
        breakdown["retries_cost_usd"] = 0.0
        return breakdown

    def _is_warmup_cycle(self) -> bool:
        return self._cycle_count < self.settings.safety.warmup_cycles or os.getenv("ARENA_WARMUP_MODE", "").lower() in {"1", "true", "yes"}

    def _ensure_not_killed(self) -> None:
        kill_file = self.settings.resolve_path(self.settings.safety.kill_switch_file)
        env_kill = os.getenv("ARENA_KILL_SWITCH", "").lower() in {"1", "true", "yes"}
        if env_kill or kill_file.exists():
            self.repository.save_health_check("global_kill_switch", "FAIL", True, "Kill switch is active")
            raise RuntimeError("global kill switch is active; competition cycle aborted")

    def _save_benchmark(self, market_state: MarketState) -> None:
        first = self.repository.first_market_snapshot()
        start_price = first.current_price if first else market_state.current_price
        self.repository.save_benchmark(
            "buy_and_hold_btc",
            start_price=start_price,
            current_price=market_state.current_price,
            payload={
                "description": "Benchmark assumes buying BTC at the first recorded market snapshot and holding.",
                "snapshot_symbol": market_state.symbol,
            },
        )

    def _save_checkpoint(self, market_state: MarketState, status: str, cycle_number: int | None = None) -> None:
        checkpoint_cycle = self._cycle_count + 1 if cycle_number is None else cycle_number
        payload = build_checkpoint_payload(
            self.repository,
            [agent.id for agent in self.settings.agents],
            self.settings.accounts.initial_equity,
            market_state.current_price,
            checkpoint_cycle,
        )
        payload["config_version"] = {
            "id": self.config_manager.config_version_id,
            "hash": self.config_manager.config_hash,
            "code_version": self.config_manager.code_version,
        }
        payload["competition_metadata"] = {
            "name": self.settings.competition.name,
            "symbol": self.settings.competition.display_symbol,
            "duration_days": self.settings.competition.duration_days,
            "poll_interval_seconds": self.settings.competition.poll_interval_seconds,
        }
        payload["token_usage"] = {agent.id: self.repository.response_usage(agent.id) for agent in self.settings.agents}
        payload["api_costs"] = {
            "total": sum(self.repository.response_usage(agent.id).get("estimated_cost_usd", 0.0) for agent in self.settings.agents),
            "by_agent": {agent.id: self.repository.response_usage(agent.id).get("estimated_cost_usd", 0.0) for agent in self.settings.agents},
        }
        payload["dashboard_snapshot"] = {
            "path": self.settings.cloud_dashboard.snapshot_path,
            "enabled": self.settings.cloud_dashboard.enabled,
            "git_auto_push": self.settings.cloud_dashboard.git_auto_push,
        }
        payload["versions"] = self.update_manager.current_versions()
        payload["prompt_versions"] = {
            "system_prompt_hash": _sha256(self.system_prompt),
            "rulebook_hash": _sha256(self.rulebook),
        }
        checkpoint_id = self.repository.save_checkpoint(checkpoint_cycle, status, payload)
        self.update_manager.write_checkpoint_file(payload, checkpoint_id, checkpoint_cycle, status)
        self.repository.save_health_check("checkpoint", "PASS", False, f"Saved checkpoint {checkpoint_id} for cycle {checkpoint_cycle}")

    def _mark_runner_state(
        self,
        status: str,
        phase: str,
        cycle_number: int,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        next_cycle_at: datetime | None = None,
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.repository.save_runner_state(
                status=status,
                phase=phase,
                cycle_number=cycle_number,
                started_at=started_at,
                completed_at=completed_at,
                next_cycle_at=next_cycle_at,
                message=message,
                payload=payload,
            )
        except Exception as error:
            logger.warning("runner state update failed without stopping trading: {}", error)

    def _current_completed_cycle_number(self) -> int:
        latest = self.repository.latest_checkpoint()
        latest_cycle = int(latest.cycle_number) if latest else 0
        return max(self._cycle_count, latest_cycle)

    def _competition_time_pct(self) -> float:
        start = self.repository.competition_start_time()
        if not start:
            return 0.0
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        else:
            start = start.astimezone(UTC)
        total = max(1.0, self.settings.competition.duration_days * 86400)
        elapsed = max(0.0, (datetime.now(UTC) - start).total_seconds())
        return min(1.0, elapsed / total)

    def _persist_daily_metrics(self, market_state: MarketState, workload: WorkloadTracker | None = None) -> None:
        rows = calculate_leaderboard(
            self.repository,
            [agent.id for agent in self.settings.agents],
            self.settings.accounts.initial_equity,
            market_state.current_price,
        )
        for row in rows:
            self.repository.save_daily_metric(
                row.agent_id,
                equity=row.equity,
                realized_pnl=row.realized_pnl,
                unrealized_pnl=row.unrealized_pnl,
                max_drawdown=row.max_drawdown_pct,
            )
            reflect_on_day(self.memory, row.agent_id, row.equity, row.realized_pnl, row.unrealized_pnl)
            if workload:
                workload.reflection(row.agent_id)

    def _append_signal_output(self, agent_id: str, raw: str, accepted: bool, reasons: list[str]) -> None:
        path = self.settings.resolve_path(self.settings.paths.signals)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n\n## {_now_utc7_iso()} - {agent_id}\n\n")
            handle.write(f"Validation: {'ACCEPTED' if accepted else 'REJECTED'}\n\n")
            if reasons:
                handle.write("Reasons:\n")
                for reason in reasons:
                    handle.write(f"- {reason}\n")
                handle.write("\n")
            handle.write("```json\n")
            handle.write(raw)
            handle.write("\n```\n")

    def _write_outputs(self, market_state: MarketState) -> None:
        self._write_ledger()
        self._write_evaluation(market_state)

    def _write_ledger(self) -> None:
        path = self.settings.resolve_path(self.settings.paths.ledger)
        path.parent.mkdir(parents=True, exist_ok=True)
        trades = self.repository.trades()
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "trade_id",
                    "agent_id",
                    "position_id",
                    "opened_at",
                    "closed_at",
                    "symbol",
                    "direction",
                    "action",
                    "status",
                    "leverage",
                    "margin",
                    "notional",
                    "entry",
                    "average_entry",
                    "stop_loss",
                    "take_profit_1",
                    "take_profit_2",
                    "exit_price",
                    "realized_pnl",
                    "unrealized_pnl",
                    "config_version_id",
                    "config_hash",
                    "code_version",
                    "notes",
                ]
            )
            positions = {position.id: position for position in self.repository.all_positions()}
            for trade in trades:
                position = positions.get(trade.position_id)
                writer.writerow(
                    [
                        trade.id,
                        trade.agent_id,
                        trade.position_id,
                        position.opened_at.isoformat() if position else "",
                        position.closed_at.isoformat() if position and position.closed_at else "",
                        position.symbol if position else "BTC",
                        trade.direction,
                        trade.action,
                        position.status if position else "",
                        trade.leverage,
                        trade.margin,
                        trade.notional,
                        trade.entry,
                        position.average_entry if position else "",
                        position.stop_loss if position else "",
                        position.take_profit_1 if position else "",
                        position.take_profit_2 if position else "",
                        trade.exit_price or "",
                        trade.realized_pnl,
                        "",
                        trade.config_version_id or "",
                        trade.config_hash,
                        trade.code_version,
                        trade.notes,
                    ]
                )

    def _write_evaluation(self, market_state: MarketState) -> None:
        rows = calculate_leaderboard(
            self.repository,
            [agent.id for agent in self.settings.agents],
            self.settings.accounts.initial_equity,
            market_state.current_price,
        )
        path = self.settings.resolve_path(self.settings.paths.evaluation)
        with path.open("w", encoding="utf-8") as handle:
            handle.write("# Evaluation\n\n")
            handle.write(f"Updated: {_now_utc7_iso()}\n\n")
            handle.write("| Agent | Equity | Return % | Sharpe | Max DD % | Rejected | Score |\n")
            handle.write("| --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
            for row in rows:
                handle.write(
                    f"| {row.agent_id} | {row.equity:.2f} | {row.total_return_pct*100:.2f} | "
                    f"{row.sharpe:.2f} | {row.max_drawdown_pct*100:.2f} | {row.rejected_signals} | {row.score:.3f} |\n"
                )
        if rows:
            self.repository.save_competition_result(
                rows[0].agent_id,
                {"updated_at": datetime.now(UTC).isoformat(), "rows": [row.model_dump() for row in rows]},
            )


def _candles_to_frame(market_state: MarketState):
    import pandas as pd

    return pd.DataFrame([c.model_dump() for c in market_state.candles])


def _compact_prompt_context(context: dict) -> dict:
    compact = dict(context)
    market = dict(compact.get("market_state") or {})
    candles = market.get("recent_candles")
    if isinstance(candles, list):
        market["recent_candles"] = candles[-3:]
    compact["market_state"] = market
    compact["similar_trades"] = _compact_json_value(compact.get("similar_trades", []), list_limit=5, string_limit=700)
    compact["private_lessons"] = _compact_json_value(compact.get("private_lessons", []), list_limit=5, string_limit=700)
    compact["shared_lessons"] = _compact_json_value(compact.get("shared_lessons", []), list_limit=5, string_limit=700)
    compact["backtest_diagnostic"] = _compact_json_value(compact.get("backtest_diagnostic", {}), list_limit=5, string_limit=700)
    return _compact_json_value(compact, list_limit=10, string_limit=1200)


def _minimal_prompt_context(context: dict) -> dict:
    keys = [
        "market_state",
        "account_summary",
        "backtest_diagnostic",
        "strategy_profile",
        "shared_learning",
        "feature_flags",
        "version_context",
    ]
    minimal = {key: context.get(key) for key in keys if key in context}
    minimal["private_lessons"] = _compact_json_value(context.get("private_lessons", []), list_limit=2, string_limit=400)
    minimal["shared_lessons"] = _compact_json_value(context.get("shared_lessons", []), list_limit=2, string_limit=400)
    return _compact_json_value(minimal, list_limit=5, string_limit=700)


def _compact_json_value(value, list_limit: int, string_limit: int):
    if isinstance(value, dict):
        return {str(key): _compact_json_value(item, list_limit, string_limit) for key, item in value.items()}
    if isinstance(value, list):
        items = [_compact_json_value(item, list_limit, string_limit) for item in value[:list_limit]]
        if len(value) > list_limit:
            items.append({"truncated_items": len(value) - list_limit})
        return items
    if isinstance(value, str) and len(value) > string_limit:
        return value[:string_limit] + f"... [truncated {len(value) - string_limit} chars]"
    return value


def _truncate_text(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + f"... [truncated {len(value) - limit} chars]"


def _parse_tool_request(raw: str) -> list[dict] | None:
    try:
        payload = json.loads(_extract_json_object(raw))
    except (JSONDecodeError, ValueError):
        return None
    requests = payload.get("tool_requests") if isinstance(payload, dict) else None
    if not isinstance(requests, list):
        return None
    parsed = [item for item in requests if isinstance(item, dict) and "tool" in item]
    return parsed or None


def _extract_json_object(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        import re

        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    if cleaned.startswith("{"):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return cleaned[start : end + 1]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now_utc7_iso() -> str:
    return datetime.now(UTC).astimezone(timezone(timedelta(hours=7))).isoformat()
