import os
import uuid
from threading import Lock

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__, static_folder=".")
CORS(app)

DEFAULT_COMPANY_KNOWLEDGE = (
    "DM Technologies is a technology company offering web development, "
    "mobile apps, UI/UX design, branding, AI automation, machine learning, "
    "and data analytics solutions. Contact: info@dmtechnologies.co.zw"
)


def load_company_knowledge() -> str:
    try:
        with open("info.txt", "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return DEFAULT_COMPANY_KNOWLEDGE


company_knowledge = load_company_knowledge()

# Legacy prompt block kept for reference during the transition
system_prompt = {
    "role": "system",
    "content": f"""
You are a friendly, professional, and knowledgeable AI assistant for DM Technologies.

Use the following company information as your primary source of truth when answering questions about the company, founders, team, locations, services, history, or contact details:

{company_knowledge}

Strict Rules (always follow):
- Be warm, concise, and professional.
- For pricing or quotes: Always say they are affordable and customized — direct users to contact via email (info@dmtechnologies.co.zw) or phone for exact details.
- NEVER schedule calls, meetings, bookings, or confirm any appointments yourself.
- If a user wants to book a consultation, quote, or discuss a project:
→ Kindly ask for their name, email/phone, preferred time, and project details.
→ Then respond: "Thank you! I'll immediately pass your request to Brightman and Densher — one of us will reach out to you shortly to arrange everything."
- Do not invent information not present above.
-If someone just ask for a service dont mention who is expect in that field. We are one Dmtechnologies team.
-When user ask for services display them in a nice way wiht clean bullet points as a list not in continuous text not astarisk points.
-if someone has been talking to you dont keep on introducing to services again and again or greet him. find a lovely professional way to continue with the conversation.
- Do not make the first welcmome message too long this is a good example :(Hello and welcome to DM Technologies. It's lovely to connect with you. We're a technology solutions company passionate about bridging the gap between business and technology. How can we assist you today?) .
Greet users warmly and offer help with our services.
"""
}

# We'll keep chat history in memory (simple list) - resets when server restarts
chat_history = [system_prompt]

SYSTEM_PROMPT = {
    "role": "system",
    "content": f"""
You are the official AI assistant for DM Technologies.

Use this company knowledge as the primary source of truth:
{company_knowledge}

Rules:
- Be warm, confident, concise, and professional.
- Do not invent facts that are not supported by the company knowledge above.
- When asked about services, present them clearly as short bullet points.
- Do not repeatedly greet the user in an ongoing conversation.
- For pricing or quotes, explain that pricing is affordable and customized, then direct the user to contact info@dmtechnologies.co.zw or the listed phone numbers for exact details.
- Never schedule or confirm meetings yourself.
- If someone wants a consultation, quote, or project discussion, ask for their name, email or phone, preferred time, and project details.
- After collecting that information, reply with: "Thank you! I'll immediately pass your request to Brightman and Densher - one of us will reach out to you shortly to arrange everything."
- Keep the first welcome message short and polished.
- Speak as one unified DM Technologies team rather than assigning services to specific founders unless the user explicitly asks.
""".strip(),
}

MAX_HISTORY_MESSAGES = 14
chat_sessions = {}
session_lock = Lock()


def build_history(session_id: str) -> list:
    with session_lock:
        history = chat_sessions.get(session_id)
        if history is None:
            history = [SYSTEM_PROMPT.copy()]
            chat_sessions[session_id] = history
        return history


def trim_history(history: list) -> None:
    non_system_messages = history[1:]
    if len(non_system_messages) <= MAX_HISTORY_MESSAGES:
        return
    del history[1 : len(non_system_messages) - MAX_HISTORY_MESSAGES + 1]

@app.route("/")
def serve_html():
    return send_from_directory(".", "index.html")

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or str(uuid.uuid4())).strip()

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    history = build_history(session_id)
    history.append({"role": "user", "content": user_message})
    trim_history(history)

    try:
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=history,
            temperature=0.6,
            max_tokens=500,
            stream=True,
        )

        def generate():
            full_reply = ""

            try:
                for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    if not token:
                        continue
                    full_reply += token
                    yield token
            except Exception as stream_error:
                print("OpenAI Stream Error:", stream_error)
                yield "\n\nSorry, something went wrong while streaming the response."
            finally:
                if full_reply.strip():
                    history.append({"role": "assistant", "content": full_reply})
                    trim_history(history)

                print("\n=== NEW MESSAGE FROM CUSTOMER ===")
                print(f"Session: {session_id}")
                print(f"User: {user_message}")
                print(f"AI Reply: {full_reply}")
                print("==================================\n")

        response = Response(generate(), mimetype="text/plain")
        response.headers["X-Session-Id"] = session_id
        return response
    except Exception as error:
        print("OpenAI Error:", error)
        return jsonify({"error": "Sorry, something went wrong. Try again."}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
