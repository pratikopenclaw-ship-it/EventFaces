import pytest

from app.services.drive_ids import parse_drive_folder_id

ID = "1AbCdEfGhIjKlMnOpQrStUv"


@pytest.mark.parametrize(
    "value",
    [
        ID,
        f"https://drive.google.com/drive/folders/{ID}",
        f"https://drive.google.com/drive/folders/{ID}?usp=sharing",
        f"https://drive.google.com/drive/u/1/folders/{ID}",
        f"https://drive.google.com/open?id={ID}",
    ],
)
def test_parses_valid(value: str) -> None:
    assert parse_drive_folder_id(value) == ID


@pytest.mark.parametrize("value", ["", "short", "https://example.com/folders/" + ID, "a b c d e f g h i j"])
def test_rejects_invalid(value: str) -> None:
    assert parse_drive_folder_id(value) is None
