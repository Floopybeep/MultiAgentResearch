class Usage:
    def __init__(self):
        self.input_tokens = 0
        self.cached_input_tokens = 0
        self.cache_usage_known = True
        self.output_tokens = 0
        self.calls = 0
        self.cost = 0.0
        self.cost_known = True

    def add(self, metadata, config):
        self.calls += 1
        if not metadata:
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
        return dict(
            input_tokens=self.input_tokens,
            cached_input_tokens=self.cached_input_tokens if self.cache_usage_known else None,
            output_tokens=self.output_tokens,
            model_calls=self.calls,
            estimated_cost_usd=self.cost if self.cost_known else None,
        )
