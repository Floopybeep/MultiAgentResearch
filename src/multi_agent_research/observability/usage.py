class Usage:
    def __init__(self):
        self.input_tokens = 0
        self.cached_input_tokens = 0
        self.cache_usage_known = True
        self.output_tokens = 0
        self.calls = 0
        self.unreported_calls = 0
        self.cost = 0.0
        self.cost_known = True
        self.duration_seconds = 0.0
        self.by_role = {}

    def add(self, metadata, config):
        self.calls += 1
        if not metadata:
            self.unreported_calls += 1
            self.cost_known = False
            self.cache_usage_known = False
            return
        incoming, outgoing = metadata.get("input_tokens", 0), metadata.get("output_tokens", 0)
        self.input_tokens += incoming
        self.output_tokens += outgoing
        cached = (metadata.get("input_token_details") or {}).get("cache_read")
        if cached is None:
            self.cache_usage_known = False
        else:
            self.cached_input_tokens += cached
        # Missing cache details use ordinary input pricing, not an assumed discount.
        cached = cached or 0
        if (
            config.input_cost_per_million is None or config.output_cost_per_million is None
            or (cached and config.cached_input_cost_per_million is None)
        ):
            self.cost_known = False
        else:
            self.cost += (
                (incoming - cached) * config.input_cost_per_million
                + cached * (config.cached_input_cost_per_million or 0)
                + outgoing * config.output_cost_per_million
            ) / 1_000_000

    def as_dict(self):
        result = dict(
            input_tokens=self.input_tokens,
            cached_input_tokens=self.cached_input_tokens if self.cache_usage_known else None,
            output_tokens=self.output_tokens,
            total_tokens=self.input_tokens + self.output_tokens,
            model_calls=self.calls,
            unreported_calls=self.unreported_calls,
            usage_complete=self.unreported_calls == 0,
            estimated_cost_usd=self.cost if self.cost_known else None,
            duration_seconds=self.duration_seconds,
        )
        if self.by_role:
            result["by_role"] = {role: usage.as_dict() for role, usage in self.by_role.items()}
        return result


def sum_usage(usages):
    """Sum recorded usage without turning unknown costs/cache counts into zero."""
    usages = list(usages)
    result = {
        key: sum(u.get(key, 0) for u in usages)
        for key in (
            "input_tokens", "output_tokens", "model_calls", "unreported_calls", "duration_seconds",
        )
    }
    for key in ("cached_input_tokens", "estimated_cost_usd"):
        result[key] = (
            sum(u[key] for u in usages)
            if all(u.get(key) is not None for u in usages) else None
        )
    result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    result["usage_complete"] = all(u.get("usage_complete", True) for u in usages)
    roles = {role for u in usages for role in u.get("by_role", {})}
    if roles:
        result["by_role"] = {
            role: sum_usage(u["by_role"][role] for u in usages if role in u.get("by_role", {}))
            for role in sorted(roles)
        }
    return result
