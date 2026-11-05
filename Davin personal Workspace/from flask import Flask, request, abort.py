from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# Ganti dengan Channel Access Token & Channel Secret dari LINE Developers Console kamu
LINE_CHANNEL_ACCESS_TOKEN = 'YOUR_CHANNEL_ACCESS_TOKEN'
LINE_CHANNEL_SECRET = 'YOUR_CHANNEL_SECRET'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/callback", methods=['POST'])
def callback():
    # Ambil signature header dari LINE
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    # REVISI PENTING: Wajib kembalikan status HTTP 200 OK secara instan agar LINE tidak melakukann retry/spamming!
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text
    
    # Menyiapkan 1 balasan resmi saja
    reply_text = f"Halo Davin, pesan kamu sudah diterima oleh Dvly Assistant: '{user_text}'"

    # Mengirim balasan tepat 1 kali menggunakan reply_token
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    print("🚀 LINE Webhook Server running on port 5000...")
    app.run(port=5000)