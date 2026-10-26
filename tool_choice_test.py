"""Run a real model tool-choice test; requires a configured local .env.

The printed score is evidence for report section 5.2. Do not call this script
with a fake client when reporting a real model score.
"""

import time

from agent import build_database, run_agent


TEST_SET = [
    ("What time are you open?", {"get_shop_info"}),
    ("Can I bring my own parts?", {"get_shop_info"}),
    ("What is the warranty on service labor?", {"get_shop_info"}),
    ("你們可以刷卡嗎？", {"get_shop_info"}),
    ("How much is SSD installation?", {"find_catalog"}),
    ("Is liquid cooling installation available?", {"find_catalog"}),
    ("16GB DDR4 RAM 多少錢？", {"find_catalog"}),
    ("What do you charge for cable management?", {"find_catalog"}),
    (
        "For a desktop, what would SSD installation with a 1TB SSD cost?",
        {"calculate_repair_quote"},
    ),
    (
        "What if I decline a laptop RAM repair after diagnosis?",
        {"calculate_repair_quote"},
    ),
    ("I want to complain to a technician.", {"transfer_to_human"}),
    ("What is the manager's personal phone number?", {"transfer_to_human"}),
]


def main():
    build_database()
    correct = 0
    for question, acceptable in TEST_SET:
        _, trace = run_agent([{"role": "user", "content": question}])
        used = {entry["tool"] for entry in trace}
        hit = bool(acceptable & used)
        correct += hit
        print(
            f"{'OK  ' if hit else 'MISS'} {question} | "
            f"expected={sorted(acceptable)} used={sorted(used)}",
            flush=True,
        )
        time.sleep(6)
    print(f"tool choice = {correct}/{len(TEST_SET)}")


if __name__ == "__main__":
    main()

