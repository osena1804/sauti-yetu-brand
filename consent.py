"""All consent wording for Sauti-Yetu lives in this one file, so a lawyer can edit it
without touching the app.

HOW TO FINALISE (do these only after your lawyer has approved the wording):
  1. Edit the text below.
  2. Change CONSENT_VERSION (for example to "v1.0"). Every report stores the version
     it was submitted under, so you can always show what the person agreed to.
  3. Set WORDING_IS_DRAFT = False.
  4. Set the three environment variables below (or edit the defaults).
"""
import os

import settings

# Bump this whenever the wording changes in any way.
CONSENT_VERSION = "v0.1-draft"
WORDING_IS_DRAFT = True

CONTROLLER_NAME = os.environ.get("SAUTI_CONTROLLER_NAME", f"{settings.CLIENT_NAME} [to be confirmed]")
PRIVACY_CONTACT = os.environ.get("SAUTI_PRIVACY_CONTACT", "[privacy contact to be confirmed]")
RETENTION_EN = os.environ.get("SAUTI_RETENTION_EN", "30 days")
RETENTION_SW = os.environ.get("SAUTI_RETENTION_SW", "siku 30")

if WORDING_IS_DRAFT:
    print("[consent] WARNING: consent wording is a DRAFT. Get it approved by a lawyer before collecting real data.")
if "[" in PRIVACY_CONTACT:
    print("[consent] WARNING: SAUTI_PRIVACY_CONTACT is not set. People need a real contact to withdraw consent.")

_EN = {
    "heading": "Before you report",
    #"draft_note": "⚠️ Draft wording, pending legal review.",
    "notice_title": "How we use your report (please read)",
    "notice_body": (
        "**Who we are.** This service is run by Sauti-Yetu for {controller}, which decides how your report is used.\n\n"
        "**What we collect.** What you write, any photos you upload, your county, and your phone number only if you "
        "give it. Our servers also record technical details, such as when you submitted.\n\n"
        "**Why.** To find and respond to product problems and suspected counterfeit products, and to check whether "
        "a fix has worked for the people affected. We do not use your report for marketing and we do not sell it.\n\n"
        "**Sensitive information.** If you describe a health problem, such as a skin reaction, or upload a photo of "
        "it, that is sensitive information. You do not have to include it.\n\n"
        "**Who sees it.** Authorised reviewers at {controller} and Sauti-Yetu. Service providers process it for us: "
        "cloud hosting, an AI language service that reads your text after we remove phone numbers, emails and ID "
        "numbers, and an SMS provider if you ask for updates. Some of these may process data outside Kenya, under "
        "written agreements.\n\n"
        "**How long.** We delete personal data {period} after your report is resolved.\n\n"
        "**Your rights.** You can ask to see, correct or delete your report, or withdraw your consent, by contacting "
        "{contact} and quoting your reference number. You can also complain to the Office of the Data Protection "
        "Commissioner.\n\n"
        "**Please** do not include names or other personal details, and do not photograph people."
    ),
    "consent_main": "I am 18 or over. I have read this notice and I agree that my report may be processed as described.",
    "consent_health": "I understand my report or photos may include health information, and I agree to it being processed as described.",
    "consent_sms": "Optional: you may send me an SMS about the outcome of my report (only if I entered a phone number).",
    "need_consent": "Tick the consent box above to enable Submit.",
    "withdraw_hint": "To withdraw your consent or ask for your report to be deleted, contact {contact} and quote this reference number.",
}

_SW = {
    "heading": "Kabla ya kutuma ripoti",
    "draft_note": "⚠️ Maneno ya rasimu, yanasubiri ukaguzi wa kisheria.",
    "notice_title": "Jinsi tunavyotumia ripoti yako (tafadhali soma)",
    "notice_body": (
        "**Sisi ni nani.** Huduma hii inaendeshwa na Sauti-Yetu kwa niaba ya {controller}, ambaye huamua jinsi ripoti "
        "yako inavyotumika.\n\n"
        "**Tunakusanya nini.** Unachoandika, picha unazopakia, kaunti yako, na namba yako ya simu ikiwa tu utaitoa. "
        "Seva zetu pia hurekodi maelezo ya kiufundi, kama wakati uliotuma ripoti.\n\n"
        "**Kwa nini.** Ili kutambua na kushughulikia matatizo ya bidhaa na bidhaa zinazoshukiwa kuwa bandia, na "
        "kuangalia kama suluhisho limefanya kazi kwa walioathirika. Hatutumii ripoti yako kwa matangazo wala "
        "hatuiuzi.\n\n"
        "**Taarifa nyeti.** Ukieleza tatizo la kiafya, kama athari kwenye ngozi, au ukipakia picha yake, hiyo ni "
        "taarifa nyeti. Si lazima kuiweka.\n\n"
        "**Nani anaiona.** Wakaguzi walioidhinishwa wa {controller} na Sauti-Yetu. Watoa huduma hushughulikia data "
        "kwa niaba yetu: uhifadhi wa wingu (cloud), huduma ya AI inayosoma maandishi yako baada ya sisi kuondoa "
        "namba za simu, barua pepe na namba za vitambulisho, na mtoa huduma wa SMS ukiomba taarifa. Baadhi yao "
        "wanaweza kushughulikia data nje ya Kenya, chini ya mikataba iliyoandikwa.\n\n"
        "**Muda wa kuhifadhi.** Tunafuta data binafsi {period} baada ya ripoti yako kushughulikiwa.\n\n"
        "**Haki zako.** Unaweza kuomba kuona, kusahihisha au kufuta ripoti yako, au kuondoa idhini yako, kwa "
        "kuwasiliana na {contact} ukitaja nambari yako ya kumbukumbu. Unaweza pia kuwasilisha malalamiko kwa Ofisi "
        "ya Kamishna wa Ulinzi wa Data.\n\n"
        "**Tafadhali** usiweke majina au maelezo mengine binafsi, na usipige picha za watu."
    ),
    "consent_main": "Nina umri wa miaka 18 au zaidi. Nimesoma ilani hii na ninakubali ripoti yangu ishughulikiwe kama ilivyoelezwa.",
    "consent_health": "Naelewa kuwa ripoti au picha zangu zinaweza kuwa na taarifa za kiafya, na ninakubali zishughulikiwe kama ilivyoelezwa.",
    "consent_sms": "Hiari: mnaweza kunitumia SMS kuhusu matokeo ya ripoti yangu (ikiwa nimeweka namba ya simu).",
    "need_consent": "Weka alama kwenye kisanduku cha idhini hapo juu ili kuwezesha kutuma.",
    "withdraw_hint": "Ili kuondoa idhini yako au kuomba ripoti yako ifutwe, wasiliana na {contact} ukitaja nambari hii ya kumbukumbu.",
}

LANGUAGES = ["English", "Kiswahili"]


def get_text(language):
    """Returns the wording for 'English' or 'Kiswahili', with the controller name,
    contact and retention period filled in. Unknown languages fall back to English."""
    base, period = (_SW, RETENTION_SW) if language == "Kiswahili" else (_EN, RETENTION_EN)
    values = {"controller": CONTROLLER_NAME, "contact": PRIVACY_CONTACT, "period": period}
    return {key: text.format(**values) for key, text in base.items()}