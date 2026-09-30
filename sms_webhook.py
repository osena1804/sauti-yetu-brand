from flask import Flask, request

import ingestion
import sms_gateway
import sms_router

app = Flask(__name__)


@app.route("/", methods=["GET"])
def health():
    return "Sauti-Yetu SMS webhook is running.", 200


@app.route("/sms/inbound", methods=["POST"])
def inbound_sms():
    """Africa's Talking POSTs form-encoded fields here: from, to, text, date, id, linkId.
    Docs: https://developers.africastalking.com/docs/sms/inbound"""
    sender = request.form.get("from", "")
    text = request.form.get("text", "")

    if not sender or not text.strip():
        return "Missing from/text", 400

    brand_name = sms_router.extract_brand_from_text(text)
    if not brand_name:
        sms_gateway.send_sms(
            sender,
            "Sorry, we couldn't tell which brand your message is about. "
            "Please include the brand name, e.g. 'Naivas: no milk on shelves at Ngong Road'."
        )
        return "OK - no brand match", 200

    county = sms_router.extract_county_from_text(text)

    try:
        result = ingestion.submit_complaint(
            brand_name=brand_name, phone=sender, county=county, text=text,
        )
        sms_gateway.send_sms(
            sender,
            f"Thank you! Your report on {brand_name} has been received. "
            f"Reference: #{result['incident_id']}."
        )
    except ValueError as e:
        sms_gateway.send_sms(sender, f"Sorry, we couldn't process that report: {e}")
        return "OK - validation error", 200
    except Exception as e:
        sms_gateway.send_sms(sender, "Sorry, something went wrong processing your report. Please try again.")
        return "OK - unexpected error, logged", 200  # still 200 so AT doesn't retry-storm you


if __name__ == "__main__":
    app.run(port=5001, debug=False)