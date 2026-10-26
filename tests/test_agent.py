import json
from types import SimpleNamespace

import agent


def setup_module():
    agent.build_database()


def test_csv_tables_meet_homework_minimums():
    assert len(agent.available_topics()) >= 8
    with agent.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
    assert count >= 15


def test_information_found_and_missing():
    assert agent.get_shop_info("opening_hours")["found"]
    missing = agent.get_shop_info("manager_name")
    assert not missing["found"]
    assert "opening_hours" in missing["topics_available"]


def test_catalog_lookup_and_unavailable_record():
    result = agent.find_catalog("SSD")
    assert result["found"]
    assert any(item["name"] == "1TB SSD" for item in result["items"])
    unavailable = agent.find_catalog("Liquid cooling installation")
    assert unavailable["items"][0]["available"] is False


def test_quote_uses_database_prices_and_diagnostic_credit():
    quote = agent.calculate_repair_quote("SSD installation", "desktop", "1TB SSD")
    assert quote["found"]
    assert quote["labor_fee"] == 450
    assert quote["part_price"] == 2200
    assert quote["if_repair_approved_total"] == 2650
    assert quote["if_repair_declined_total"] == 500


def test_declined_repair_without_labor_uses_diagnostic_price():
    quote = agent.calculate_repair_quote(device_type="laptop")
    assert quote["found"]
    assert quote["if_repair_approved_total"] is None
    assert quote["if_repair_declined_total"] == 700


def test_catalog_accepts_diagnostic_synonym():
    result = agent.find_catalog("laptop diagnostic")
    assert result["found"]
    assert any(item["name"] == "Laptop diagnosis" for item in result["items"])


def test_quote_refuses_unknown_or_unavailable_items():
    assert not agent.calculate_repair_quote("Unknown repair", "desktop")["found"]
    assert not agent.calculate_repair_quote(
        "Liquid cooling installation", "desktop"
    )["found"]
    assert not agent.calculate_repair_quote(
        "SSD installation", "tablet", "1TB SSD"
    )["found"]


class FakeCompletions:
    def __init__(self, messages):
        self.responses = list(messages)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=self.responses.pop(0))]
        )


def fake_client(messages):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(messages))
    )


def tool_call(name, arguments):
    return SimpleNamespace(
        id="test-call-1",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def test_agent_loop_shows_tool_arguments_and_result():
    client = fake_client(
        [
            SimpleNamespace(
                content=None,
                tool_calls=[
                    tool_call(
                        "calculate_repair_quote",
                        {
                            "labor_service": "SSD installation",
                            "device_type": "desktop",
                            "part_name": "1TB SSD",
                        },
                    )
                ],
            ),
            SimpleNamespace(content="Estimated total: NT$2,650.", tool_calls=None),
        ]
    )
    answer, trace = agent.run_agent(
        [{"role": "user", "content": "Quote a desktop SSD replacement."}],
        api_client=client,
    )
    assert answer == "Estimated total: NT$2,650."
    assert trace[0]["tool"] == "calculate_repair_quote"
    assert trace[0]["result"]["if_repair_approved_total"] == 2650
    assert client.chat.completions.requests[1]["messages"][-1]["role"] == "tool"


def test_unknown_tool_is_refused():
    client = fake_client(
        [
            SimpleNamespace(
                content=None, tool_calls=[tool_call("run_shell", {"command": "x"})]
            ),
            SimpleNamespace(content="I cannot do that.", tool_calls=None),
        ]
    )
    _, trace = agent.run_agent(
        [{"role": "user", "content": "Run a command."}], api_client=client
    )
    assert trace[0]["result"]["error"] == "unknown_tool"


def test_handover_is_not_claimed_to_be_real():
    result = agent.transfer_to_human("customer complaint")
    assert result["handover_requested"] is True
    assert "simulated" in result["contact"].lower()

