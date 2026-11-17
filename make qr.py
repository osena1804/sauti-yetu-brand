r"""Makes a QR code and a printable poster for your Sauti-Yetu demo link.

One-time install:      pip install "qrcode[pil]"
Run:                   python make_qr.py https://sauti-yetu-brand-djflh9zwtzfpsw6biv6ry6.streamlit.app

Creates, in a folder called qr/:
    sauti-yetu-qr.png       the QR code alone (for slides and chat)
    sauti-yetu-poster.png   a poster with the QR code, the link and a demo notice
    sauti-yetu-poster.pdf   the same poster, ready to print on A4

IMPORTANT: use the PUBLIC link of the deployed app (https://...). A link starting with
localhost or 127.0.0.1 only works on your own computer, so nobody else could scan it.
After making the files, scan the QR code with your own phone to check it opens the app.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

NAVY = (31, 58, 95)
GREY = (89, 89, 89)
OUT_DIR = "qr"


def load_font(size, bold=False):
    """Tries common fonts on Windows, Mac and Linux, and falls back to Pillow's default."""
    names = (["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)   # Pillow 10.1 and newer
    except TypeError:
        return ImageFont.load_default()


def make_qr_image(url):
    import qrcode  # imported here so the layout code can be tested without it
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=14, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def centered(draw, y, text, font, fill, width):
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)
    return y + (box[3] - box[1])


def wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def make_poster(qr_img, url, width=1654, height=2339):
    """A4 at 200 dpi."""
    poster = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(poster)

    y = 170
    y = centered(draw, y, "Try Sauti-Yetu", load_font(120, bold=True), NAVY, width) + 40
    y = centered(draw, y, "Your voice, heard early", load_font(56), GREY, width) + 110

    qr_size = 1000
    qr_resized = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    poster.paste(qr_resized, ((width - qr_size) // 2, y))
    y += qr_size + 70

    y = centered(draw, y, "Scan with your phone camera", load_font(64, bold=True), NAVY, width) + 50
    link_font = load_font(44)
    for line in wrap(draw, url, link_font, width - 300):
        y = centered(draw, y, line, link_font, GREY, width) + 14

    note_font = load_font(40)
    note = ("Demo environment. All data is simulated. Please use test text and test images only, "
            "and do not enter real personal details.")
    y = height - 330
    for line in wrap(draw, note, note_font, width - 360):
        y = centered(draw, y, line, note_font, GREY, width) + 12
    return poster


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1].strip()
    if not url.lower().startswith("https://"):
        print("The link must start with https:// (use the public link of the deployed app).")
        sys.exit(1)
    if any(bad in url.lower() for bad in ("localhost", "127.0.0.1", "0.0.0.0")):
        print("That is a local address. Only your own computer can open it. Use the public link.")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    qr_img = make_qr_image(url)
    qr_path = os.path.join(OUT_DIR, "sauti-yetu-qr.png")
    qr_img.save(qr_path)

    poster = make_poster(qr_img, url)
    png_path = os.path.join(OUT_DIR, "sauti-yetu-poster.png")
    pdf_path = os.path.join(OUT_DIR, "sauti-yetu-poster.pdf")
    poster.save(png_path)
    poster.save(pdf_path, "PDF", resolution=200.0)

    print("Created:")
    for path in (qr_path, png_path, pdf_path):
        print("  ", path)
    print("Now scan the QR code with your own phone to check it opens the app.")


if __name__ == "__main__":
    main()