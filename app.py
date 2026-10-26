"""Gradio front end for the ByteForge PC Workshop course-demo agent.

Run: python app.py
"""

import traceback

import gradio as gr

from agent import build_database, run_agent


INFO_COUNT, RECORD_COUNT = build_database()
print(f"Ready: {INFO_COUNT} information topics and {RECORD_COUNT} catalog records.")

GREETING = (
    "Welcome to ByteForge PC Workshop, a fictional course-demo PC shop. "
    "Ask about our assembly or repair services, prices, or shop policies.\n\n"
    "歡迎來到 ByteForge 電腦工坊（課程虛構店家）。您可以詢問組裝、維修、價格與店家規則。"
)


def start_chat():
    return [{"role": "assistant", "content": GREETING}]


def add_user_message(text, history):
    text = (text or "").strip()
    if not text:
        return "", history
    return "", history + [{"role": "user", "content": text}]


def answer_question(history):
    if not history or history[-1]["role"] != "user":
        return history, []
    try:
        answer, trace = run_agent(history)
    except RuntimeError:
        answer = (
            "The model is not configured. Copy .env.example to .env and set "
            "LLM_API_URL, MODEL_NAME, and API_KEY."
        )
        trace = []
    except Exception as error:
        frames = traceback.extract_tb(error.__traceback__)
        where = [(frame.name, frame.lineno) for frame in frames[-4:]]
        roles = [entry.get("role") for entry in history if isinstance(entry, dict)]
        content_types = [type(entry.get("content")).__name__ for entry in history if isinstance(entry, dict)]
        content_keys = [list(entry["content"]) if isinstance(entry.get("content"), dict) else [] for entry in history if isinstance(entry, dict)]
        print(f"Agent call failed: {type(error).__name__}; where={where}; roles={roles}; types={content_types}; keys={content_keys}")
        answer = "The service could not answer right now. Please check the server log."
        trace = []
    return history + [{"role": "assistant", "content": answer}], trace


SAMPLE_QUESTIONS_EN = [
    "What time are you open?",
    "Can I bring my own PC parts?",
    "How much is SSD installation?",
    "Is liquid cooling installation available?",
    "For a desktop, what is the total if you install a 1TB SSD?",
    "What if I decline that repair after diagnosis?",
    "My PC shuts down randomly. Can you diagnose it right now?",
    "What is the manager's personal phone number?",
    "What is the weather tomorrow?",
]

SAMPLE_QUESTIONS_ZH = [
    "你們星期日有營業嗎？",
    "可以自備零件組裝電腦嗎？",
    "SSD 安裝服務多少錢？",
    "桌機安裝 1TB SSD，維修估價是多少？",
    "如果我不同意維修，只做檢測要付多少？",
    "我要找真人技師，電腦一直當機。",
]


with gr.Blocks(title="ByteForge PC Workshop Customer Service") as demo:
    gr.Markdown(
        "## ByteForge PC Workshop Customer Service\n"
        "A fictional computer assembly and repair shop for the Unit G assignment. "
        "The agent chooses database and calculation tools; the panel shows each call. "
        "No real booking or technician contact is made."
    )
    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                value=start_chat(), height=450, label="Conversation"
            )
            with gr.Row():
                user_box = gr.Textbox(
                    placeholder="Ask about PC services or workshop policies...",
                    show_label=False,
                    scale=8,
                )
                send_button = gr.Button("Send", variant="primary", scale=1)
                clear_button = gr.Button("Clear", scale=1)
            gr.Markdown("Choose a sample question, then press Send.")
            with gr.Tabs():
                with gr.Tab("English"):
                    gr.Examples(SAMPLE_QUESTIONS_EN, inputs=user_box)
                with gr.Tab("中文"):
                    gr.Examples(SAMPLE_QUESTIONS_ZH, inputs=user_box)
        with gr.Column(scale=2):
            trace_panel = gr.JSON(label="Tools used: arguments and results", value=[], elem_id="tool-trace")

    send_button.click(
        add_user_message, [user_box, chatbot], [user_box, chatbot]
    ).then(answer_question, chatbot, [chatbot, trace_panel])
    user_box.submit(
        add_user_message, [user_box, chatbot], [user_box, chatbot]
    ).then(answer_question, chatbot, [chatbot, trace_panel])
    clear_button.click(
        lambda: (start_chat(), "", []),
        outputs=[chatbot, user_box, trace_panel],
    )


if __name__ == "__main__":
    demo.launch(
        share=False,
        css="#tool-trace .value.string { color: #8b2e0d !important; } "
            "#tool-trace .key { color: #24517a !important; }",
    )
