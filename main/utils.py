import io
import re
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

_FONTS = None


def _fonts():
    """O‘, g‘ kabi harflarni to'g'ri chiqarish uchun reportlab bilan keladigan Vera shriftini ulaydi."""
    global _FONTS
    if _FONTS is None:
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
            pdfmetrics.registerFont(TTFont("VeraBd", "VeraBd.ttf"))
            _FONTS = ("Vera", "VeraBd")
        except Exception:
            _FONTS = ("Helvetica", "Helvetica-Bold")
    return _FONTS


def _results_pdf(title_html, header, rows, col_widths, header_color=colors.black):
    regular, bold = _fonts()
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    styles["Title"].fontName = bold
    story = [Paragraph(title_html, styles["Title"]), Spacer(1, 12)]

    table = Table([header] + rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke),
        ('TEXTCOLOR', (0, 0), (-1, 0), header_color),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), bold),
        ('FONTNAME', (0, 1), (-1, -1), regular),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    story.append(table)
    pdf.build(story)
    buffer.seek(0)
    return buffer


def generate_test_result_pdf(test, results):
    """Milliy sertifikat testi natijalari (hisobla_statistika natijalari ro'yxati) bo'yicha PDF."""
    title = (
        f"<b><font size=16 color='blue'>{escape(test.title)} natijalari.</font></b><br/>"
        f"<font size=12 color='blue'>Test kodi: {test.id}</font>"
    )
    rows = [
        [
            i,
            r.get("full_name") or "Noma'lum",
            round(r['score'], 2),
            f"{r['percent']}",
            r['grade'] if r.get('grade') != 'not_sertificate' else '-',
        ]
        for i, r in enumerate(results, start=1)
    ]
    return _results_pdf(title, ["T/r", "Ism Familiya", "Ball", "Foiz", "Daraja"], rows,
                        [30, 200, 70, 70, 70], header_color=colors.red)


def generate_block_test_result_pdf(test, results):
    """Blok (DTM) test natijalari: o'rin, ism, to'g'ri javob, ball."""
    title = (
        "<b><font size=16 color='blue'>Blok Test Natijalari</font></b><br/>"
        f"<font size=12 color='black'>ID: {test.id}</font><br/>"
        f"<font size=12 color='black'>Sana: {timezone.localtime():%d.%m.%Y}</font>"
    )
    rows = [[r['rank'], r['full_name'], r['correct_answers'], r['score']] for r in results]
    return _results_pdf(title, ["O'rin", "Ism Familiya", "To'g'ri javoblar", "Ball"], rows, [40, 250, 100, 70])


# ---------------------------------------------------------------------------
# Milliy sertifikat: Rasch bo'yicha savol ballari va darajalar
# ---------------------------------------------------------------------------

def calculate_rasch(correct_answers, total_students, min_ball=0.5, epsilon=1.0, jami_ball=100):
    """Har bir savol uchun ball: kam odam topgan (qiyin) savolga ko'proq ball, jami `jami_ball`."""
    if not correct_answers:
        return []
    if total_students <= 0:
        return [round(jami_ball / len(correct_answers), 4)] * len(correct_answers)

    qiyinlik = [1 - c / total_students for c in correct_answers]
    qiyinlik_adj = [q + epsilon for q in qiyinlik]
    jami_qiyinlik = sum(qiyinlik_adj)
    ogirlik = [q / jami_qiyinlik for q in qiyinlik_adj]
    asosiy_ball = [o * jami_ball for o in ogirlik]

    min_current = min(asosiy_ball)
    max_current = max(asosiy_ball)
    n = len(correct_answers)

    if min_current < min_ball and max_current - min_current * n:
        scale_factor = (jami_ball - min_ball * n) / (max_current - min_current * n)
        ball = [min_ball + (b - min_current) * scale_factor for b in asosiy_ball]
    else:
        ball = [b / max_current * jami_ball for b in asosiy_ball]

    jami_current = sum(ball)
    if jami_current and abs(jami_current - jami_ball) > 1e-6:
        ball = [round(b * (jami_ball / jami_current), 4) for b in ball]
    return ball


def calculate_student_scores(result, savol_ballari):
    """O'quvchining jami bali va har bir savol bo'yicha olgan ballari."""
    oquvchi_javoblari = getattr(result, 'user_answers', None) or []
    jami_ball = 0
    toplangan_ballar = []
    for i, javob in enumerate(oquvchi_javoblari):
        if javob == 1 and i < len(savol_ballari):
            jami_ball += savol_ballari[i]
            toplangan_ballar.append(savol_ballari[i])
        else:
            toplangan_ballar.append(0)
    return {"result": result, "jami_ball": jami_ball, "toplangan_ballar": toplangan_ballar}


def daraja_va_foiz(ball):
    """Milliy sertifikat darajasi va daraja ichidagi foiz."""
    if ball >= 70:
        return "A+", "100 %"
    if ball >= 65:
        return "A", "100 %"
    if ball >= 60:
        return "B+", f"{min(99, round(90 + ((ball - 60) / 5) * 9, 0))} %"
    if ball >= 55:
        return "B", f"{min(89, round(85 + ((ball - 55) / 5) * 4, 0))} %"
    if ball >= 50:
        return "C+", f"{min(84, round(80 + ((ball - 50) / 5) * 4, 0))} %"
    if ball >= 46:
        return "C", f"{min(79, round(70 + ((ball - 46) / 4) * 9, 0))} %"
    return "not_sertificate", "—"


def hisobla_statistika(results, max_ball=80):
    categories = {"A+": 0, "A": 0, "B+": 0, "B": 0, "C+": 0, "C": 0, "not_sertificate": 0}

    natijalar = []
    for item in results:
        ball = float(item["jami_ball"])
        daraja, foiz = daraja_va_foiz(ball)
        categories[daraja] += 1
        natijalar.append({
            "full_name": str(item["result"]).split(" - ")[0],
            "score": round(ball, 2),
            "percent": foiz,
            "grade": daraja,
        })

    natijalar.sort(key=lambda x: x["score"], reverse=True)
    jami = len(results)
    statistika = {
        k: f"{v} ta ({round((v / jami) * 100, 1) if jami else 0}%)" for k, v in categories.items()
    }
    return {"statistika": statistika, "natijalar": natijalar}


# ---------------------------------------------------------------------------
# Reklama matni: [[Matn](URL)] -> havola, [[Tugma|URL]] -> inline tugma
# ---------------------------------------------------------------------------

LINK_PATTERN = re.compile(r"\[\[(.*?)\]\((.*?)\)\]")
BUTTON_PATTERN = re.compile(r"\[\[(.*?)\|(.*?)\]\]")


def parse_reklama_text(raw_text: str) -> Tuple[str, List[Dict]]:
    """(Telegram HTML matn, [{"text": ..., "url": ...}]) qaytaradi."""
    buttons = []

    def button_replacer(match):
        buttons.append({"text": match.group(1).strip(), "url": match.group(2).strip()})
        return ""

    text_without_buttons = BUTTON_PATTERN.sub(button_replacer, raw_text or "")
    parsed_text = LINK_PATTERN.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text_without_buttons)
    return parsed_text.strip(), buttons
