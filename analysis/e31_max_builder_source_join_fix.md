Issue17 Max authoring only no tools. Return minimal unified diff scripts/prepare_e31_submission.py only. Notebook source is list[str], current code passes list to ast.parse, must join. Current exactlines:
    src_cells = [_code_cell(cells[i]["source"]) for i in (3, 5, 7, 9)]
    cell11_src = cells[11]["source"]
    marker = "def list_test_stems() -> list[str]:"
    prefix = cell11_src[: cell11_src.index(marker)]
Fix first to _code_cell("".join(cells[i]["source"])); second to "".join(cells[11]["source"]); add assert cell11_src.count(marker)==1 between marker and prefix. Nothing else.
