from xalpha.universe import classify_board, is_v01_execution_candidate


def test_board_classification():
    assert classify_board("600000") == "SSE_MAIN"
    assert classify_board("000001") == "SZSE_MAIN"
    assert classify_board("300750") == "CHINEXT"
    assert classify_board("688981") == "STAR"


def test_execution_gate_is_conservative():
    assert is_v01_execution_candidate("600000", name="浦发银行") is True
    assert is_v01_execution_candidate("300750", name="宁德时代") is False
    assert is_v01_execution_candidate("600001", name="*ST示例") is False
    assert is_v01_execution_candidate("600002", suspended=True) is False
    assert is_v01_execution_candidate("600003", one_price_limit=True) is False
