import pytest

from app.payload.application.payload_input import PayloadInput, UnequalListsError


def test_sample_renders_as_the_task_shows() -> None:
    payload_input = PayloadInput(
        list_1=("first string", "second string", "third string"),
        list_2=("other string", "another string", "last string"),
    )
    transformations = {text: text.upper() for text in payload_input.texts()}

    output = payload_input.render(transformations)

    assert output == "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"


def test_lists_of_different_lengths_are_rejected() -> None:
    with pytest.raises(UnequalListsError) as raised:
        PayloadInput(list_1=("a", "b"), list_2=("c",))

    assert raised.value.code == "unequal_lists"
    assert raised.value.details == {"list_1_length": 2, "list_2_length": 1}


def test_equal_inputs_have_equal_fingerprints() -> None:
    first = PayloadInput(list_1=("a", "b"), list_2=("c", "d"))
    second = PayloadInput(list_1=("a", "b"), list_2=("c", "d"))

    assert first.fingerprint() == second.fingerprint()


@pytest.mark.parametrize(
    "other",
    [
        pytest.param(PayloadInput(list_1=("b", "a"), list_2=("c", "d")), id="order"),
        pytest.param(PayloadInput(list_1=("a", "b"), list_2=("d", "c")), id="order in list_2"),
        pytest.param(PayloadInput(list_1=("c", "d"), list_2=("a", "b")), id="sides"),
        pytest.param(PayloadInput(list_1=("a", "bc"), list_2=("d", "")), id="boundary"),
        pytest.param(PayloadInput(list_1=("A", "B"), list_2=("C", "D")), id="same output"),
    ],
)
def test_a_different_input_has_a_different_fingerprint(other: PayloadInput) -> None:
    payload_input = PayloadInput(list_1=("a", "b"), list_2=("c", "d"))

    assert payload_input.fingerprint() != other.fingerprint()


@pytest.mark.parametrize(
    ("payload_input", "fingerprint"),
    [
        pytest.param(
            PayloadInput(
                list_1=("first string", "second string", "third string"),
                list_2=("other string", "another string", "last string"),
            ),
            "db1643219a6c379b295897e1daa542e2a58690ab61fa70c673de661c46068a2f",
            id="sample",
        ),
        pytest.param(
            PayloadInput(list_1=("Straße",), list_2=('\N{GRINNING FACE} "quoted"',)),
            "9bfe30e39a24289c9f4fb4a67492504ed55a43757b9119c0dcb7aaf093404ba5",
            id="escaped",
        ),
    ],
)
def test_the_fingerprint_scheme_does_not_change(payload_input: PayloadInput, fingerprint: str) -> None:
    assert payload_input.fingerprint() == fingerprint
