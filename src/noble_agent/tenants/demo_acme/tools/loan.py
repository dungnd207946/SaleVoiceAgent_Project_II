# Demo/isolation-fixture custom tool for the `demo_acme` tenant. This is NOT
# a real product tool — it exists solely to prove, through the real boot
# path (tenant/loader.py::_import_tenant_tools's pkgutil walk), that dropping
# one file under tenants/<id>/tools/ self-registers a custom @tool with no
# core edit. Only active if TENANT_ID=demo_acme, which no deploy sets.
from noble_agent.agent.tools.registry import tool

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_loan",
        "description": "Kiểm tra điều kiện vay (custom tool demo của demo_acme).",
        "parameters": {"type": "object", "properties": {"amount": {"type": "number"}}, "required": []},
    },
}


@tool(name="check_loan", schema=_SCHEMA, tenant="demo_acme", read_only=True)
async def check_loan(args, *, provider, tenant, **_):
    return f"loan:{tenant}:{args.get('amount', 0)}"
