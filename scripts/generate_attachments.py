"""
Generates synthetic proof-of-rate attachment files (PNG/JPG "screenshots",
PDF quotes, DOC/RTF confirmation emails) for every filename referenced in
Attachment1..Attachment5 of the claims CSV.

Usage:
    python scripts/generate_attachments.py [--csv data/brg_claims.csv] [--out data/attachments]
"""

import argparse
import json
import os
import random

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from fpdf import FPDF

ATTACHMENT_COLS = ["Attachment1", "Attachment2", "Attachment3", "Attachment4", "Attachment5"]

IMG_W, IMG_H = 900, 560
BG = (255, 255, 255)
NAVY = (20, 40, 90)
GRAY = (90, 90, 90)
GREEN = (20, 130, 60)
LINE = (210, 214, 220)


def _font(size, bold=False):
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


FONT_TITLE = _font(30, bold=True)
FONT_H2 = _font(20, bold=True)
FONT_BODY = _font(16)
FONT_SMALL = _font(13)
FONT_PRICE = _font(42, bold=True)


def itinerary_summary(row):
    bt = row["BookingType"]
    if bt == "Flight":
        return f"{row.get('Origin', '')} -> {row.get('Destination', '')}  |  {row.get('Airline', '')} ({row.get('FareClass', '')})"
    if bt == "Hotel/Lodging":
        return f"{row.get('PropertyName', 'Hotel')}  |  {row.get('RoomType', '')} room, {row.get('MealPlan', '')}"
    if bt == "Car":
        return f"{row.get('RentalCompany', '')} {row.get('VehicleClass', '')}  |  {row.get('PickupLocation', '')} -> {row.get('DropoffLocation', '')}"
    if bt == "Cruise":
        return f"{row.get('CruiseLine', '')} {row.get('ShipName', '')}  |  {row.get('CabinType', '')} cabin"
    if bt == "Package":
        try:
            segs = json.loads(row.get("SegmentList") or "[]")
            types = ", ".join(s["SegmentType"] for s in segs)
        except Exception:
            types = "Multi-segment package"
        return f"Package: {types}"
    return bt


def make_screenshot(row, path, fmt):
    img = Image.new("RGB", (IMG_W, IMG_H), BG)
    d = ImageDraw.Draw(img)

    vendor = row.get("BetterRateVendorName", "Vendor")
    amount = row.get("BetterRateAmount", 0)
    currency = row.get("BookingCurrency", "USD") or "USD"
    itinerary = itinerary_summary(row)
    travel_start = row.get("TravelStartDate", "")
    travel_end = row.get("TravelEndDate", "")
    n_pax = row.get("NumberOfPassengers", 1)
    url = row.get("BetterRateURL") or f"https://www.{str(vendor).lower().replace(' ', '').replace('.', '')}.com/"

    # Browser chrome mockup
    d.rectangle([0, 0, IMG_W, 46], fill=(235, 237, 240))
    d.rectangle([0, 46, IMG_W, 48], fill=LINE)
    d.ellipse([16, 16, 30, 30], fill=(255, 95, 86))
    d.ellipse([38, 16, 52, 30], fill=(255, 189, 46))
    d.ellipse([60, 16, 74, 30], fill=(39, 201, 63))
    d.rectangle([100, 10, IMG_W - 20, 36], outline=LINE, width=1)
    d.text((112, 15), str(url)[:80], font=FONT_SMALL, fill=GRAY)

    # Header / vendor banner
    d.rectangle([0, 48, IMG_W, 110], fill=NAVY)
    d.text((30, 66), str(vendor), font=FONT_TITLE, fill=(255, 255, 255))

    y = 140
    d.text((30, y), "Your selected rate", font=FONT_H2, fill=(30, 30, 30))
    y += 36
    d.text((30, y), itinerary, font=FONT_BODY, fill=(40, 40, 40))
    y += 30
    d.text((30, y), f"Travel dates: {travel_start} to {travel_end}", font=FONT_BODY, fill=GRAY)
    y += 26
    d.text((30, y), f"Guests / Passengers: {n_pax}", font=FONT_BODY, fill=GRAY)
    y += 26
    d.text((30, y), f"Rate type: Publicly available, no membership required", font=FONT_BODY, fill=GRAY)

    d.rectangle([30, y + 40, IMG_W - 30, y + 46], fill=LINE)

    y2 = y + 70
    d.text((30, y2), "Total price", font=FONT_H2, fill=(30, 30, 30))
    d.text((30, y2 + 36), f"{currency} ${amount:,.2f}", font=FONT_PRICE, fill=GREEN)

    d.rectangle([IMG_W - 230, y2 + 20, IMG_W - 40, y2 + 68], fill=GREEN)
    d.text((IMG_W - 215, y2 + 34), "Book This Rate", font=FONT_BODY, fill=(255, 255, 255))

    d.rectangle([0, IMG_H - 34, IMG_W, IMG_H], fill=(245, 246, 248))
    d.text((30, IMG_H - 26), f"Captured for BRG claim {row.get('CaseID', '')} — screenshot proof", font=FONT_SMALL, fill=GRAY)

    if fmt == "JPG":
        img.convert("RGB").save(path, "JPEG", quality=88)
    else:
        img.save(path, "PNG")


def make_pdf(row, path):
    vendor = row.get("BetterRateVendorName", "Vendor")
    amount = row.get("BetterRateAmount", 0)
    currency = row.get("BookingCurrency", "USD") or "USD"
    itinerary = itinerary_summary(row)
    travel_start = row.get("TravelStartDate", "")
    travel_end = row.get("TravelEndDate", "")
    case_id = row.get("CaseID", "")
    conf_no = f"CNF-{abs(hash(case_id)) % 10_000_000:07d}"

    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(20, 40, 90)
    pdf.cell(0, 12, str(vendor), ln=True)

    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 8, "Rate Quote / Booking Confirmation", ln=True)
    pdf.ln(4)

    pdf.set_draw_color(210, 214, 220)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(50, 8, "Confirmation No:")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, conf_no, ln=True)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(50, 8, "Itinerary:")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 8, str(itinerary))

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(50, 8, "Travel Dates:")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, f"{travel_start} to {travel_end}", ln=True)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(50, 8, "Fare/Rate Terms:")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, str(row.get("FareOrRatePlanFlexibility", "")), ln=True)

    pdf.ln(6)
    pdf.set_draw_color(210, 214, 220)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(20, 130, 60)
    pdf.cell(0, 10, f"Total Price: {currency} ${amount:,.2f}", ln=True)

    pdf.ln(10)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(140, 140, 140)
    pdf.multi_cell(0, 6, f"This document is a synthetic rate quote generated for BRG claim {case_id}. Not a real transaction.")

    pdf.output(path)


def rtf_escape(text):
    return str(text).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def make_doc(row, path):
    vendor = row.get("BetterRateVendorName", "Vendor")
    amount = row.get("BetterRateAmount", 0)
    currency = row.get("BookingCurrency", "USD") or "USD"
    itinerary = itinerary_summary(row)
    travel_start = row.get("TravelStartDate", "")
    travel_end = row.get("TravelEndDate", "")
    case_id = row.get("CaseID", "")
    first = row.get("FirstName", "Customer")
    last = row.get("LastName", "")
    conf_no = f"CNF-{abs(hash(case_id)) % 10_000_000:07d}"
    sub_date = str(row.get("ClaimSubmissionDate", ""))[:10]

    lines = [
        f"From: reservations@{str(vendor).lower().replace(' ', '').replace('.', '')}.com",
        f"To: {rtf_escape(first)}.{rtf_escape(last)}@example.com",
        f"Date: {sub_date}",
        f"Subject: Your booking confirmation - {rtf_escape(vendor)}",
        "",
        f"Dear {rtf_escape(first)} {rtf_escape(last)},",
        "",
        f"Thank you for booking with {rtf_escape(vendor)}. Your reservation is confirmed.",
        "",
        f"Confirmation Number: {conf_no}",
        f"Itinerary: {rtf_escape(itinerary)}",
        f"Travel Dates: {travel_start} to {travel_end}",
        f"Rate Terms: {rtf_escape(row.get('FareOrRatePlanFlexibility', ''))}",
        f"Total Price: {currency} ${amount:,.2f}",
        "",
        "This rate was publicly available at the time of booking and required no",
        "special membership, corporate code, or loyalty program enrollment.",
        "",
        "Thank you for choosing us.",
        f"{rtf_escape(vendor)} Reservations Team",
        "",
        f"[Synthetic confirmation generated for BRG claim {rtf_escape(case_id)} - not a real transaction]",
    ]

    rtf_body = "\\par\n".join(lines)
    rtf = (
        "{\\rtf1\\ansi\\deff0"
        "{\\fonttbl{\\f0 Calibri;}}"
        "\\f0\\fs22 "
        + rtf_body
        + "}"
    )
    with open(path, "w", encoding="ascii", errors="replace") as f:
        f.write(rtf)


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic attachment files referenced by the claims CSV")
    parser.add_argument("--csv", type=str, default="data/brg_claims.csv")
    parser.add_argument("--out", type=str, default="data/attachments")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    df = pd.read_csv(args.csv)
    df = df.fillna("")

    generated = {"pdf": 0, "jpg": 0, "png": 0, "doc": 0}
    skipped_existing = 0

    for _, row in df.iterrows():
        row = row.to_dict()
        for col in ATTACHMENT_COLS:
            fname = row.get(col, "")
            if not fname:
                continue
            ext = fname.rsplit(".", 1)[-1].lower()
            path = os.path.join(args.out, fname)

            if os.path.exists(path):
                skipped_existing += 1
                continue

            if ext == "pdf":
                make_pdf(row, path)
                generated["pdf"] += 1
            elif ext == "jpg":
                make_screenshot(row, path, "JPG")
                generated["jpg"] += 1
            elif ext == "png":
                make_screenshot(row, path, "PNG")
                generated["png"] += 1
            elif ext == "doc":
                make_doc(row, path)
                generated["doc"] += 1

    total = sum(generated.values())
    print(f"Generated {total:,} attachment files in {args.out}/")
    print(generated)
    if skipped_existing:
        print(f"Skipped {skipped_existing} already-existing files")


if __name__ == "__main__":
    main()
