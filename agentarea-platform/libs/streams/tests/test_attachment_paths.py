from agentarea_streams.domain.envelope import attachment_items


def test_a_last_item_path_takes_only_the_last_entry_of_a_list():
    body = {
        "message": {
            "photo": [
                {"file_id": "small", "width": 90},
                {"file_id": "medium", "width": 320},
                {"file_id": "large", "width": 1280},
            ]
        }
    }
    assert attachment_items(body, "message.photo[-1]") == [{"file_id": "large", "width": 1280}]


def test_a_last_item_path_on_an_empty_list_finds_nothing():
    assert attachment_items({"message": {"photo": []}}, "message.photo[-1]") == []
