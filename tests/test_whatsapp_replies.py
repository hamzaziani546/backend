from app.services.whatsapp_replies import (
    ReplyAction,
    extract_incoming_messages,
    parse_reply_action,
)


def test_parse_confirm_button():
    assert parse_reply_action(button_title="تأكيد الطلب") == ReplyAction.CONFIRM


def test_parse_edit_button():
    assert parse_reply_action(button_title="تعديل المعلومات") == ReplyAction.EDIT


def test_parse_cancel_button():
    assert parse_reply_action(button_title="إلغاء الطلب") == ReplyAction.CANCEL


def test_extract_button_reply():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "212627837429",
                                    "id": "wamid.test",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": "confirm_order",
                                            "title": "تأكيد الطلب",
                                        },
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    messages = extract_incoming_messages(payload)
    assert len(messages) == 1
    assert messages[0].action == ReplyAction.CONFIRM
