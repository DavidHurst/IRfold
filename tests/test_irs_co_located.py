from irfold.util import ir_pair_co_located


def test_method_ir_pair_co_located_with_co_located_ir_pair(
    co_located_ir_pair,
):
    ir_a = co_located_ir_pair[0]
    ir_b = co_located_ir_pair[1]

    assert ir_pair_co_located(ir_a, ir_b) == True


def test_method_ir_pair_co_located_with_non_co_located_ir_pair(
    non_co_located_ir_pair,
):
    ir_a = non_co_located_ir_pair[0]
    ir_b = non_co_located_ir_pair[1]

    assert ir_pair_co_located(ir_a, ir_b) == False
