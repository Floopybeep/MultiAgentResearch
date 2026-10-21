class Usage:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0
        self.cost = 0.0
        self.cost_known = True

    def add(self, metadata, config):
        self.calls += 1
        if not metadata:
            self.cost_known = False
            return
        incoming, outgoing = metadata.get("input_tokens", 0), metadata.get("output_tokens", 0)
        self.input_tokens += incoming
        self.output_tokens += outgoing
        if config.input_cost_per_million is None or config.output_cost_per_million is None:
            self.cost_known = False
        else:
            self.cost += (
                incoming * config.input_cost_per_million + outgoing * config.output_cost_per_million
            ) / 1_000_000

    def as_dict(self):
        return dict(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model_calls=self.calls,
            estimated_cost_usd=self.cost if self.cost_known else None,
        )
