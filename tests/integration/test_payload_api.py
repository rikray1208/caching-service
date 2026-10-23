from fastapi.testclient import TestClient

SAMPLE_INPUT = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}
SAMPLE_OUTPUT = "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"


def test_sample_is_created_and_read_back_as_the_task_shows(client: TestClient) -> None:
    created = client.post("/payload", json=SAMPLE_INPUT)

    assert created.status_code == 201
    assert created.json()["message"] == "Payload created."

    read = client.get(f"/payload/{created.json()['id']}")

    assert read.status_code == 200
    assert read.json() == {"output": SAMPLE_OUTPUT}
