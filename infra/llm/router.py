#!/usr/bin/env python3
"""
Model routing and fallback logic for LLM requests.

Provides ModelRouter class to manage primary model with fallback chain,
enabling automatic retry with alternative models when primary fails.
"""

from typing import List, Optional, Tuple


class ModelRouter:
    """
    Manages model selection with fallback strategy.

    Tracks primary model and fallback chain, advancing through models
    when requests fail. Used by LLMBatchClient to retry failed requests
    with alternate models.

    Thread Safety:
        Router instances are per-request and not shared across threads.
        No locking needed as each request has its own router instance.

    Example:
        >>> router = ModelRouter("x-ai/grok-4-fast", ["anthropic/claude-opus", "openai/gpt-4o"])
        >>> router.get_current()
        'x-ai/grok-4-fast'
        >>> router.has_fallback()
        True
        >>> router.next_model()
        'anthropic/claude-opus'
        >>> router.get_current()
        'anthropic/claude-opus'
    """

    def __init__(self, primary_model: str, fallback_models: Optional[List[str]] = None):
        """
        Initialize router with primary and fallback models.

        Args:
            primary_model: Primary model to try first (e.g., "x-ai/grok-4-fast")
            fallback_models: Optional list of fallback models to try in order
                           (e.g., ["anthropic/claude-opus", "openai/gpt-4o"])
        """
        if not primary_model:
            raise ValueError("primary_model cannot be empty")

        self.primary_model = primary_model
        self.fallback_models = fallback_models or []
        self.models = [primary_model] + self.fallback_models
        self.current_index = 0
        self.attempts: List[Tuple[str, bool]] = []  # Track (model, success) pairs

    def get_current(self) -> str:
        """
        Get currently active model.

        Returns:
            Model name to use for next request attempt
        """
        return self.models[self.current_index]

    def has_fallback(self) -> bool:
        """
        Check if fallback models are available.

        Returns:
            True if there are more models to try, False if exhausted
        """
        return self.current_index < len(self.models) - 1

    def next_model(self) -> Optional[str]:
        """
        Advance to next fallback model.

        Records current model as failed and advances to next model in chain.

        Returns:
            Next model name if available, None if no more fallbacks
        """
        if not self.has_fallback():
            return None

        # Record current model as failed
        self.attempts.append((self.models[self.current_index], False))

        # Advance to next model
        self.current_index += 1
        return self.models[self.current_index]

    def mark_success(self):
        """
        Mark current model as successful.

        Should be called when a request succeeds with current model.
        Used for telemetry and attempt history tracking.
        """
        self.attempts.append((self.get_current(), True))

    def get_attempt_history(self) -> List[Tuple[str, bool]]:
        """
        Get list of all model attempts.

        Returns:
            List of (model_name, success) tuples showing attempt history

        Example:
            [("x-ai/grok-4-fast", False), ("anthropic/claude-opus", True)]
        """
        return self.attempts.copy()

    def get_models_attempted(self) -> List[str]:
        """
        Get list of models that were attempted (failed + current).

        Returns:
            List of model names that have been tried
        """
        attempted = [model for model, _ in self.attempts]
        # If we're mid-attempt (no success marked yet), include current model
        if not any(success for _, success in self.attempts):
            attempted.append(self.get_current())
        return attempted

    def __repr__(self):
        """String representation for debugging."""
        return (f"ModelRouter(current={self.get_current()}, "
                f"attempts={len(self.attempts)}, "
                f"has_fallback={self.has_fallback()})")
