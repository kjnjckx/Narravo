import json
from pydantic import create_model
from narravo_engine.contracts import METHODS
models = {model.__name__: (model, ...) for pair in METHODS.values() for model in pair}
contract = create_model("Contracts", **models)
print(json.dumps({"schema": contract.model_json_schema(), "methods": {
    method: [params.__name__, result.__name__] for method, (params, result) in METHODS.items()
}}))
