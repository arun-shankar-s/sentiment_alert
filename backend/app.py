from flask import Flask,request,jsonify,send_from_directory
from transformers import pipeline
import requests
import os


classifier = pipeline("text-classification", model="distilbert-base-uncased-finetuned-sst-2-english")


tag_classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

TEAM_LABELS = ["Delivery Team", "Product Team", "Billing Team", "Support Team", "General Team"]

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"  
API_URL="http://127.0.0.1:5000/analyze"


ALLOWED_TAGS=["@stride"]

feedback_stats = {
    "Delivery Team": {"positive": 0, "negative": 0},
    "Product Team": {"positive": 0, "negative": 0},
    "Billing Team": {"positive": 0, "negative": 0},
    "Support Team": {"positive": 0, "negative": 0},
    "General Team": {"positive": 0, "negative": 0}
}

app=Flask(__name__)
# Path to frontend folder
FRONTEND_FOLDER = os.path.join(os.path.dirname(__file__), "../frontend")

# Serve index.html
@app.route("/")
def home():
    return send_from_directory(FRONTEND_FOLDER, "index.html")

# Serve any other file in the frontend folder (images, css, js)
@app.route("/<path:filename>")
def serve_file(filename):
    return send_from_directory(FRONTEND_FOLDER, filename)


def get_template_reply(comment):
    comment_lower = comment.lower()

    TEMPLATES = {
    "service": "We're sorry for the inconvenience. Our support team will assist you immediately.",
    "delivery": "We apologize for the delay. We'll ensure your order arrives promptly.",
    "product quality": "We're sorry the product didn't meet your expectations. We'll help you resolve this.",
    "billing": "We apologize for any billing issues. Our team will resolve this promptly.",
    "default": "We're sorry for your experience. Our support team will contact you shortly."
    }

    if "service" in comment_lower or "hate" in comment_lower:
        return TEMPLATES["service"]
    elif "delivery" in comment_lower or "late" in comment_lower:
        return TEMPLATES["delivery"]
    elif "product" in comment_lower or "quality" in comment_lower:
        return TEMPLATES["product quality"]
    elif "bill" in comment_lower or "charge" in comment_lower:
        return TEMPLATES["billing"]
    else:
        return TEMPLATES["default"]
    
def get_team_to_tag(comment):
    result = tag_classifier(comment, TEAM_LABELS)
    return result['labels'][0]
    

def send_slack_alert(comment,sentiment,confidence):   
    team=get_team_to_tag(comment)

    if sentiment =="NEGATIVE":
        reply = get_template_reply(comment)    
        if confidence > 95:
            level = "very high"
        elif confidence > 90:
            level = "high"
        elif confidence>85:
            level = "medium"
        message = {
                    "text": f"""\n\n\n
            🚨 Negative comment detected!
            💬 Comment: {comment}
            📊 Level: {level}
            💡 Suggested Reply: {reply}
            👥 Team to tag: {team}
            """
                }
    if sentiment =="POSITIVE":
        message = {
                "text": f"""\n\n\n
        ✅ Positive comment detected!
        💬 Comment: {comment}
        👥 Team to tag: {team}
        💡 Suggested Reply: Thank you for your valuable feedback 🙌
        """
            }
    try:
        response=requests.post(SLACK_WEBHOOK_URL,json=message)
        response.raise_for_status()
        print("✅ Slack alert sent.")
    except requests.exceptions.RequestException as e:
        print(f"Error sending Slack alert: {e}")


@app.route("/analyze",methods=["POST"])
def analyze():
    data=request.json
    text=data.get("text","")
    if not text:
        return jsonify({"error":"No text provided"}),400
    result=classifier(text)[0]
    return jsonify({
        "text":text,
        "sentiment":result["label"],
        "confidence":round(result["score"]*100,2)
    })


@app.route("/comment", methods=["POST"])
def comment():
    comment_text = request.form.get("comment", "")
    tag = request.form.get("tag", "")

    if not comment_text or not tag:
        return jsonify({"error": "Both comment and tag are required"}), 400

    if tag.lower() not in ALLOWED_TAGS:
        return jsonify({"error": "Comment ignored. Tag a valid company."}), 400

    # Call sentiment API
    try:
        response = requests.post(API_URL, json={"text": comment_text})
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Error calling sentiment API: {e}"}), 500

    result = response.json()
    sentiment = result.get("sentiment")
    confidence = result.get("confidence", 0)

    # Send Slack alert
    send_slack_alert(comment_text, sentiment, confidence)

    team = get_team_to_tag(comment_text)

    if sentiment == "POSITIVE":
        feedback_stats[team]["positive"] += 1
    else:
        feedback_stats[team]["negative"] += 1

    # Suggested reply
    suggested_reply = get_template_reply(comment_text) if sentiment=="NEGATIVE" else "Thank you for your valuable feedback."

    return jsonify({
        "suggested_reply": suggested_reply
    })


@app.route("/stats", methods=["GET"])
def stats():
    total_positive = sum(team["positive"] for team in feedback_stats.values())
    total_negative = sum(team["negative"] for team in feedback_stats.values())

    # Find top team
    max_team, max_count = None, 0
    for team, counts in feedback_stats.items():
        total = counts["positive"] + counts["negative"]
        if total > max_count:
            max_team, max_count = team, total

    return jsonify({
        "total_positive": total_positive,
        "total_negative": total_negative,
        "teams": feedback_stats,
        "top_team": {"name": max_team, "count": max_count}
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)
