"""Agent runtime — wraps AIAgent with per-user isolation + memory prefetch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.config_registry import ConfigRegistry
from plugins.app_gateway.redis_store import SessionHotCache
from plugins.app_gateway.session_keys import build_gateway_session_key, build_hermes_session_id
from plugins.app_gateway.vector_memory import create_user_vector_memory
from plugins.app_gateway.concurrency import AgentConcurrencyPool, AgentQueueTimeout
from plugins.app_gateway.user_scope import app_gateway_user_scope

logger = logging.getLogger(__name__)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")


def _looks_like_skill_inventory_query(content: Any) -> bool:
    text = _message_text(content).lower()
    if not text:
        return False
    mentions_skills = "skill" in text or "技能" in text
    asks_inventory = any(
        marker in text
        for marker in (
            "有哪些",
            "有什么",
            "哪些",
            "列表",
            "列出",
            "what",
            "which",
            "list",
            "available",
        )
    )
    return mentions_skills and asks_inventory


def _format_visible_skills_catalog(skills: list[dict[str, Any]], *, limit: int = 120) -> str:
    visible = [s for s in skills if not s.get("disabled")]
    lines = [
        "[Visible skills catalog]",
        "The user is asking what skills are available. Answer from this catalog. "
        "Do not say you cannot access skills.",
        "Do not answer that the user has no saved skills when shared/external "
        "skills are listed below; these skills are visible and usable by this user.",
        f"Visible skill count: {len(visible)}",
    ]
    for skill in visible[:limit]:
        name = str(skill.get("name") or "").strip()
        if not name:
            continue
        desc = str(skill.get("description") or "").strip()
        lines.append(f"- {name}: {desc}" if desc else f"- {name}")
    if len(visible) > limit:
        lines.append(f"- ... {len(visible) - limit} more skills omitted")
    return "\n".join(lines)


class AppAgentRuntime:
    """Single-process multi-user runtime (maps to tgs.html Agent Runtime)."""

    def __init__(
        self,
        config: AppGatewayConfig,
        cache: Optional[SessionHotCache] = None,
        vector_memory: Optional[Any] = None,
        config_registry: Optional[ConfigRegistry] = None,
    ) -> None:
        self._config = config
        self._cache = cache or SessionHotCache(config.redis_url, config.redis_ttl_seconds)
        self._vector = vector_memory or create_user_vector_memory(config)
        self._registry = config_registry or ConfigRegistry()
        self._session_db = None
        self._pool = AgentConcurrencyPool(
            max_concurrent=config.max_concurrent_agents,
            max_workers=config.agent_executor_workers,
            queue_timeout_seconds=config.agent_queue_timeout_seconds,
        )
        self._per_user_skills = config.per_user_skills_isolated
        self._include_global_skills = config.include_global_skills
        self._per_user_api_keys = config.per_user_api_keys
        self._fallback_global_credentials = config.fallback_global_credentials

    def _ensure_session_db(self):
        if self._session_db is None:
            from hermes_state import get_shared_session_db

            self._session_db = get_shared_session_db()
        return self._session_db

    @staticmethod
    def _text_for_prefetch(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict) and str(part.get("type") or "") == "text":
                    t = part.get("text")
                    if t:
                        texts.append(str(t))
            return "\n".join(texts)
        return str(content or "")

    def _build_ephemeral_prompt(
        self,
        ctx: UserContext,
        user_message: Any,
        *,
        client_system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        parts = []
        prefix = self._registry.get_ephemeral_system_prefix()
        if prefix:
            parts.append(prefix)
        if client_system_prompt and str(client_system_prompt).strip():
            parts.append(str(client_system_prompt).strip())
        from plugins.app_gateway.workspace_paths import WORKSPACE_TOOLS_NOTE

        parts.append(
            "[Tool policy]\n"
            f"{WORKSPACE_TOOLS_NOTE}\n"
            "You have files, skills, memory, execute_code, delegate_task, vision_analyze, "
            "and cronjob (no terminal, browser, or web_search). "
            "Answer from attachments and workspace files first; use vision_analyze for images."
        )
        if self._vector.enabled:
            block = self._vector.format_prefetch_block(
                ctx.user_id,
                self._text_for_prefetch(user_message),
            )
            if block:
                parts.append(block)
        if _looks_like_skill_inventory_query(user_message):
            try:
                from plugins.app_gateway.skills_routes import list_user_skills

                skills = list_user_skills(ctx, include_global=self._include_global_skills)
                if skills:
                    parts.append(_format_visible_skills_catalog(skills))
            except Exception as exc:
                logger.debug("Could not build visible skills catalog prompt: %s", exc)
        if not parts:
            return None
        return "\n\n".join(parts)

    def _create_agent(
        self,
        ctx: UserContext,
        *,
        session_id: str,
        gateway_session_key: str,
        ephemeral_system_prompt: Optional[str] = None,
        stream_delta_callback=None,
        tool_start_callback=None,
        tool_complete_callback=None,
    ) -> Any:
        from gateway.runtime_cache import get_gateway_agent_kit, toolsets_for_platform
        from hermes_cli.config import load_config
        from hermes_cli.tools_config import _get_platform_tools
        from plugins.app_gateway.user_credentials import (
            resolve_user_model,
            resolve_user_runtime_kwargs,
        )
        from run_agent import AIAgent

        platform = self._config.platform_toolset
        kit = get_gateway_agent_kit(platform=platform)

        if self._per_user_api_keys:
            model = resolve_user_model() or kit.model
            runtime_kwargs = resolve_user_runtime_kwargs(
                fallback_global=self._fallback_global_credentials,
            )
            user_cfg = load_config()
            enabled_toolsets = list(
                sorted(_get_platform_tools(user_cfg, platform)),
            )
        else:
            from gateway.runtime_cache import get_gateway_runtime_kwargs

            model = kit.model
            runtime_kwargs = get_gateway_runtime_kwargs()
            enabled_toolsets = list(toolsets_for_platform(platform))

        max_iters = int(getattr(self._config, "agent_max_iterations", 25) or 25)
        env_cap = __import__("os").environ.get("HERMES_MAX_ITERATIONS", "").strip()
        if env_cap.isdigit():
            max_iters = int(env_cap)

        return AIAgent(
            model=model,
            **runtime_kwargs,
            max_iterations=max(1, max_iters),
            quiet_mode=True,
            enabled_toolsets=enabled_toolsets,
            session_id=session_id,
            platform="app_gateway",
            user_id=ctx.user_id,
            gateway_session_key=gateway_session_key,
            ephemeral_system_prompt=ephemeral_system_prompt,
            stream_delta_callback=stream_delta_callback,
            tool_start_callback=tool_start_callback,
            tool_complete_callback=tool_complete_callback,
            session_db=self._ensure_session_db(),
            save_session_log=bool(getattr(self._config, "session_json_snapshot", False)),
            fallback_model=kit.fallback_model,
            reasoning_config=kit.reasoning_config,
        )

    def load_history(self, ctx: UserContext, session_id: str) -> List[Dict[str, Any]]:
        db_hist: List[Dict[str, Any]] = []
        try:
            db = self._ensure_session_db()
            db_hist = db.get_messages_as_conversation(session_id) or []
        except Exception as exc:
            logger.warning("Failed to load session %s: %s", session_id, exc)
        if bool(getattr(getattr(self, "_config", None), "postgres_only", False)):
            return db_hist
        cached = self._cache.get_history(ctx.user_id, ctx.session_id)
        if cached is not None:
            # Redis tail cache can lag Postgres persistence — prefer the longer history.
            if len(db_hist) > len(cached):
                return db_hist
            return cached
        return db_hist

    async def run_chat(
        self,
        ctx: UserContext,
        user_message: Any,
        *,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        client_system_prompt: Optional[str] = None,
        stream_delta_callback: Optional[Callable] = None,
        tool_start_callback: Optional[Callable] = None,
        tool_complete_callback: Optional[Callable] = None,
        agent_ref: Optional[list] = None,
        run_id: Optional[str] = None,
        gateway_session_key: Optional[str] = None,
        event_callback: Optional[Callable] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        session_id = build_hermes_session_id(ctx)
        gsk = gateway_session_key or build_gateway_session_key(ctx)
        history = conversation_history
        if history is None:
            history = self.load_history(ctx, session_id)

        ephemeral = self._build_ephemeral_prompt(
            ctx,
            user_message,
            client_system_prompt=client_system_prompt,
        )

        def _run():
            needs_scope = self._per_user_skills or self._per_user_api_keys
            scope = (
                app_gateway_user_scope(
                    ctx,
                    include_global_skills=self._include_global_skills,
                )
                if needs_scope
                else contextlib.nullcontext()
            )
            with scope:
                agent = self._create_agent(
                    ctx,
                    session_id=session_id,
                    gateway_session_key=gsk,
                    ephemeral_system_prompt=ephemeral,
                    stream_delta_callback=stream_delta_callback,
                    tool_start_callback=tool_start_callback,
                    tool_complete_callback=tool_complete_callback,
                )
                if run_id:
                    from plugins.app_gateway.run_registry import attach_agent

                    attach_agent(run_id, agent)
                if agent_ref is not None:
                    if agent_ref:
                        agent_ref[0] = agent
                    else:
                        agent_ref.append(agent)

                def _approval_notify(approval_data: Dict[str, Any]) -> None:
                    if not event_callback:
                        return
                    event = dict(approval_data or {})
                    event.update(
                        {
                            "object": "hermes.event",
                            "type": "approval.request",
                            "run_id": run_id or session_id,
                            "choices": ["once", "session", "always", "deny"],
                        }
                    )
                    try:
                        event_callback(event)
                    except Exception:
                        pass

                approval_registered = False
                try:
                    from gateway.session_context import set_session_vars
                    from tools.approval import register_gateway_notify, unregister_gateway_notify

                    register_gateway_notify(gsk, _approval_notify)
                    approval_registered = True
                except Exception:
                    pass

                task_id = session_id
                try:
                    result = agent.run_conversation(
                        user_message=user_message,
                        conversation_history=history,
                        task_id=task_id,
                    )
                finally:
                    if approval_registered:
                        try:
                            from tools.approval import unregister_gateway_notify

                            unregister_gateway_notify(gsk)
                        except Exception:
                            pass
                usage = {
                    "input_tokens": getattr(agent, "session_prompt_tokens", 0) or 0,
                    "output_tokens": getattr(agent, "session_completion_tokens", 0) or 0,
                    "total_tokens": getattr(agent, "session_total_tokens", 0) or 0,
                }
                eff_sid = getattr(agent, "session_id", session_id)
                if isinstance(eff_sid, str) and eff_sid:
                    result["session_id"] = eff_sid
                result["gateway_session_key"] = gsk
                result["user_id"] = ctx.user_id
                if run_id:
                    result["run_id"] = run_id
                return result, usage

        try:
            result, usage = await self._pool.run(_run, user_id=ctx.user_id)
        except AgentQueueTimeout as exc:
            return (
                {
                    "final_response": str(exc),
                    "error": "queue_timeout",
                    "session_id": session_id,
                    "gateway_session_key": gateway_session_key,
                    "user_id": ctx.user_id,
                },
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            )

        async def _persist():
            try:
                messages = result.get("messages") or []
                if messages:
                    self._cache.set_history(ctx.user_id, ctx.session_id, messages)
                if self._vector.enabled:
                    final = result.get("final_response") or ""
                    summary = self._vector.summarize_turn(
                        self._text_for_prefetch(user_message),
                        final,
                    )
                    self._vector.add(ctx.user_id, ctx.session_id, summary)
            except Exception as exc:
                logger.debug("async persist failed: %s", exc)

        asyncio.create_task(_persist())
        return result, usage
