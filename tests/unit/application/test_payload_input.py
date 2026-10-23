import pytest

from payload_cache.application.payload_input import PayloadInput, UnequalListsError


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
