from shared import order_states as st


def test_happy_path_is_valid():
    path = [st.CREATED, st.SELLER_SEEN, st.CONFIRMED, st.DELIVERING, st.DONE]
    for cur, nxt in zip(path, path[1:]):
        assert st.is_valid_transition(cur, nxt)


def test_terminal_states_have_no_exits():
    for state in st.TERMINAL_STATES:
        assert st.is_terminal(state)
        assert st.TRANSITIONS[state] == frozenset()


def test_cannot_skip_or_go_backwards():
    assert not st.is_valid_transition(st.CREATED, st.DONE)
    assert not st.is_valid_transition(st.DELIVERING, st.CREATED)
    assert not st.is_valid_transition(st.DONE, st.CANCELLED)


def test_every_transition_target_is_a_known_state():
    for targets in st.TRANSITIONS.values():
        assert targets <= set(st.ORDER_STATES)
    assert set(st.TRANSITIONS) == set(st.ORDER_STATES)
