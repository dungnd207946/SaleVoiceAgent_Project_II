"""PPR expansion must run off the event loop (run_in_executor), else one
tenant's PPR blocks every other session mid-turn (memo §4)."""
import ast
import pathlib


def test_expand_is_offloaded_to_executor():
    src = pathlib.Path("src/noble_agent/agent/rag/hipporag/adapter.py").read_text()
    tree = ast.parse(src)
    # Find the assignment target `ppr_rows` and assert its value is an `await`
    # of run_in_executor (not a bare expander.expand(...) call).
    found_inline = False
    found_offloaded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ppr_rows" for t in node.targets
        ):
            v = node.value
            if isinstance(v, ast.Await):
                found_offloaded = True
            elif isinstance(v, ast.Call) and "expand" in ast.dump(v):
                found_inline = True
    assert found_offloaded and not found_inline
