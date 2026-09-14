"""Brand-styled PDF renderer for monthly club reports."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.services.monthly_report_view import format_money, format_number, format_percent

PURPLE = colors.HexColor("#8F5BFF")
PURPLE_DARK = colors.HexColor("#2A1744")
INK = colors.HexColor("#21152F")
MUTED = colors.HexColor("#746981")
PANEL = colors.HexColor("#F4F0FA")
LINE = colors.HexColor("#E4DAF2")
GREEN = colors.HexColor("#26A269")
RED = colors.HexColor("#D6455D")
LOGO_PATH = Path(__file__).resolve().parents[1] / "static" / "img" / "cyber-bonus-logo.png"


def _register_fonts() -> tuple[str, str]:
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for regular, bold in candidates:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("CBRegular", regular))
            pdfmetrics.registerFont(TTFont("CBBold", bold))
            return "CBRegular", "CBBold"
    return "Helvetica", "Helvetica-Bold"


REGULAR, BOLD = _register_fonts()


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName=BOLD,
            fontSize=25,
            leading=30,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=5 * mm,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName=BOLD, fontSize=17, leading=22, textColor=INK, spaceAfter=4 * mm
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName=BOLD, fontSize=11, leading=14, textColor=INK, spaceAfter=2 * mm
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontName=REGULAR, fontSize=8.5, leading=12, textColor=INK
        ),
        "muted": ParagraphStyle(
            "Muted", parent=base["BodyText"], fontName=REGULAR, fontSize=7.5, leading=10, textColor=MUTED
        ),
        "kpi": ParagraphStyle("KPI", parent=base["BodyText"], fontName=BOLD, fontSize=20, leading=23, textColor=PURPLE),
        "center": ParagraphStyle(
            "Center",
            parent=base["BodyText"],
            fontName=REGULAR,
            fontSize=8,
            leading=11,
            textColor=INK,
            alignment=TA_CENTER,
        ),
        "center_bold": ParagraphStyle(
            "CenterBold",
            parent=base["BodyText"],
            fontName=BOLD,
            fontSize=9,
            leading=12,
            textColor=INK,
            alignment=TA_CENTER,
        ),
        "header": ParagraphStyle(
            "Header",
            parent=base["BodyText"],
            fontName=BOLD,
            fontSize=8,
            leading=10,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "cover_brand": ParagraphStyle(
            "CoverBrand",
            parent=base["BodyText"],
            fontName=BOLD,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#D4BFFF"),
            spaceAfter=25 * mm,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName=BOLD,
            fontSize=31,
            leading=38,
            textColor=colors.white,
            alignment=TA_LEFT,
            spaceAfter=8 * mm,
        ),
        "cover_sub": ParagraphStyle(
            "CoverSub",
            parent=base["BodyText"],
            fontName=REGULAR,
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#D7CBE8"),
        ),
    }


def _page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#FBF9FD"))
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    canvas.setFont(REGULAR, 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 9 * mm, "CYBER BONUS · ЕЖЕМЕСЯЧНЫЙ ОТЧЁТ")
    canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, str(doc.page))
    canvas.restoreState()


def _cover(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#160B24"))
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#2C1552"))
    canvas.circle(A4[0] - 10 * mm, A4[1] - 15 * mm, 80 * mm, fill=1, stroke=0)
    canvas.setFillColor(PURPLE)
    canvas.circle(A4[0] - 15 * mm, 5 * mm, 45 * mm, fill=1, stroke=0)
    if LOGO_PATH.is_file():
        canvas.drawImage(
            str(LOGO_PATH),
            A4[0] - 54 * mm,
            A4[1] - 54 * mm,
            28 * mm,
            33 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )
    canvas.restoreState()


def _kpi_card(label, value, note, styles):
    return Table(
        [[Paragraph(label, styles["h2"])], [Paragraph(value, styles["kpi"])], [Paragraph(note, styles["muted"])]],
        colWidths=[53 * mm],
        rowHeights=[13 * mm, 11 * mm, 12 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("ROUNDEDCORNERS", [5 * mm]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ]
        ),
    )


def _section_title(title, note, styles):
    return KeepTogether([Paragraph(title, styles["h1"]), Paragraph(note, styles["muted"]), Spacer(1, 4 * mm)])


def _bar_rows(rows, value_key, styles, *, max_value=None, suffix=""):
    maximum = max_value or max([abs(float(row.get(value_key) or 0)) for row in rows] + [1])
    data = []
    for row in rows:
        value = float(row.get(value_key) or 0)
        width = max(2, 64 * abs(value) / maximum)
        bar = Table(
            [[""]],
            colWidths=[width * mm],
            rowHeights=[4 * mm],
            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), PURPLE if value >= 0 else RED)]),
        )
        data.append(
            [
                Paragraph(str(row.get("label") or ""), styles["body"]),
                bar,
                Paragraph(f"{format_number(value, 1)}{suffix}", styles["center_bold"]),
            ]
        )
    return Table(
        data,
        colWidths=[55 * mm, 70 * mm, 25 * mm],
        rowHeights=8 * mm,
        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]),
    )


def _data_table(headers, rows, widths, styles):
    data = [[Paragraph(header, styles["header"]) for header in headers]]
    data.extend(
        [
            [Paragraph(str(cell), styles["center"] if index else styles["body"]) for index, cell in enumerate(row)]
            for row in rows
        ]
    )
    return Table(
        data,
        colWidths=widths,
        repeatRows=1,
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PURPLE_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ]
        ),
    )


def render_monthly_report_pdf(view, output_path):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    doc = BaseDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Cyber Bonus — {view['club']['name']} — {view['period']['title']}",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[frame], onPage=_cover, autoNextPageTemplate="content"),
            PageTemplate(id="content", frames=[frame], onPage=_page, autoNextPageTemplate="content"),
        ]
    )

    story = [
        Spacer(1, 12 * mm),
        Paragraph("КИБЕР БОНУС", styles["cover_brand"]),
        Paragraph("Ежемесячный<br/>отчёт клуба", styles["cover_title"]),
        Spacer(1, 10 * mm),
        Paragraph(view["club"]["name"], styles["cover_title"]),
        Paragraph(view["period"]["title"], styles["cover_sub"]),
        Spacer(1, 63 * mm),
        Paragraph(f"Сформирован {view['generated_label']} · {view['club']['timezone']}", styles["cover_sub"]),
        PageBreak(),
        Paragraph("Главное за месяц", styles["title"]),
        Paragraph("Ключевые показатели клиентской базы и динамика к предыдущему календарному месяцу.", styles["muted"]),
        Spacer(1, 6 * mm),
    ]
    cards = [_kpi_card(card["label"], card["value"], card["change"], styles) for card in view["metric_cards"]]
    story.append(
        Table(
            [[cards[0], cards[1], cards[2]], [cards[3], cards[4], cards[5]]],
            colWidths=[57 * mm] * 3,
            rowHeights=[38 * mm, 38 * mm],
            hAlign="LEFT",
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                ]
            ),
        )
    )
    story += [
        Spacer(1, 9 * mm),
        _section_title(
            "Пульс клиентской базы",
            "Состав базы на конец месяца и чистое изменение к предыдущей контрольной точке.",
            styles,
        ),
        _bar_rows(view["pulse"], "change", styles, suffix=""),
    ]
    if view.get("data_quality"):
        story += [Spacer(1, 6 * mm), Paragraph(" · ".join(view["data_quality"]), styles["muted"])]

    story += [
        PageBreak(),
        _section_title(
            "Health Score базы",
            "Оценка регулярности и устойчивости поведения гостей по действующей HVE-логике.",
            styles,
        ),
    ]
    h = view["health"]
    health_cards = [
        _kpi_card("Health на конец месяца", h["average_label"], f"Оценено гостей: {h['scored_guests']}", styles),
        _kpi_card("Прошлый месяц", h["previous_label"], "Предыдущая контрольная точка", styles),
        _kpi_card("Изменение", format_number(h.get("change"), 1), "пункта Health Score", styles),
    ]
    story += [
        Table(
            [health_cards],
            colWidths=[57 * mm] * 3,
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ]
            ),
        ),
        Spacer(1, 8 * mm),
    ]
    story.append(_bar_rows(h["distribution"], "percent", styles, max_value=100, suffix="%"))
    story += [
        Spacer(1, 12 * mm),
        _section_title(
            "Удержание новых гостей",
            "Когорта гостей, чей первый известный визит состоялся в отчётном месяце. Возвраты учитываются по доступной истории на дату формирования.",
            styles,
        ),
    ]
    funnel = view["retention"]["new_guests"]
    story.append(
        _data_table(
            ["Этап", "Гости", "От новой когорты"],
            [
                ["1-й визит", funnel["first"], "100%" if funnel["first"] else "—"],
                ["2-й визит", funnel["second"], format_percent(funnel["second_percent"])],
                ["3-й визит", funnel["third"], format_percent(funnel["third_percent"])],
            ],
            [75 * mm, 35 * mm, 55 * mm],
            styles,
        )
    )
    story += [
        Spacer(1, 8 * mm),
        Paragraph("Частота посещений всех гостей месяца", styles["h2"]),
        _bar_rows(
            [
                {"label": f"{row['visits']}+ визит", "value": row["percent"] or 0}
                for row in view["retention"]["all_guests"]
            ],
            "value",
            styles,
            max_value=100,
            suffix="%",
        ),
    ]

    story += [
        PageBreak(),
        _section_title(
            "CRM-коммуникации",
            f"Возврат считается, если следующий визит произошёл в течение {view['crm']['attribution_days']} дней после отправки.",
            styles,
        ),
    ]
    auto = view["crm"]["automatic"]
    if auto:
        story.append(
            _data_table(
                ["Автосценарий", "Получили", "Вернулись", "Конверсия", "Пополнения"],
                [
                    [
                        row["title"],
                        row["sent"],
                        row["returned"],
                        format_percent(row["conversion_percent"]),
                        format_money(row["topup_amount"]),
                    ]
                    for row in auto
                ],
                [62 * mm, 25 * mm, 25 * mm, 28 * mm, 35 * mm],
                styles,
            )
        )
    else:
        story.append(Paragraph("Автоматические сообщения в этом месяце не отправлялись.", styles["body"]))
    story += [Spacer(1, 10 * mm), Paragraph("Лучшая ручная кампания", styles["h1"])]
    manual = view["crm"].get("best_manual")
    if manual:
        story.append(
            _data_table(
                ["Кампания", "Аудитория", "Отправлено", "Вернулись", "Конверсия", "Пополнения"],
                [
                    [
                        manual["title"],
                        manual["audience"],
                        manual["sent"],
                        manual["returned"],
                        format_percent(manual["conversion_percent"]),
                        format_money(manual["topup_amount"]),
                    ]
                ],
                [40 * mm, 42 * mm, 23 * mm, 23 * mm, 25 * mm, 28 * mm],
                styles,
            )
        )
    else:
        story.append(Paragraph("В этом месяце ручные CRM-кампании не запускались.", styles["body"]))
    story += [
        Spacer(1, 13 * mm),
        _section_title(
            "Игровые механики", "Вовлечённость считается от уникальных гостей клуба за отчётный месяц.", styles
        ),
    ]
    game_rows = []
    for label, key in (("Кейсы", "cases"), ("Колесо", "wheel"), ("Задания", "missions")):
        item = view["gamification"][key]
        game_rows.append(
            [
                label,
                item["participants"],
                item["actions"],
                format_number(item["average_actions"], 2),
                format_percent(item["engagement_percent"]),
            ]
        )
    story.append(
        _data_table(
            ["Механика", "Участники", "Действия", "В среднем", "Вовлечённость"],
            game_rows,
            [48 * mm, 28 * mm, 28 * mm, 30 * mm, 40 * mm],
            styles,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            "Для заданий хранится только факт завершения, поэтому completion rate не рассчитывается.", styles["muted"]
        )
    )

    story += [
        PageBreak(),
        _section_title(
            "Пополнения вовлечённых гостей",
            "Гости, которые открыли кейс более одного раза или завершили хотя бы одно задание. Показатель отражает связь с вовлечением, а не доказанную причинность.",
            styles,
        ),
    ]
    revenue = view["engaged_revenue"]
    rev_cards = [
        _kpi_card("Вовлечённых гостей", format_number(revenue["guests"]), "подошли под условия", styles),
        _kpi_card("С пополнением", format_number(revenue["topped_up_guests"]), "уникальных гостей", styles),
        _kpi_card(
            "Сумма пополнений", revenue["amount_label"], f"в среднем {revenue['average_label']} на вовлечённого", styles
        ),
    ]
    story.append(
        Table(
            [rev_cards],
            colWidths=[57 * mm] * 3,
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ]
            ),
        )
    )
    story += [
        Spacer(1, 14 * mm),
        _section_title(
            f"Вклад Cyber Bonus за {view['period']['title'].lower()}",
            "Итоговые показатели связаны с коммуникациями и игровыми механиками Cyber Bonus.",
            styles,
        ),
    ]
    impact = view["cyber_bonus_impact"]
    freq = impact["engaged_frequency"]
    impact_rows = [
        [
            "Возврат потерянных после авторассылки",
            impact["reactivation"]["returned"],
            f"из {impact['reactivation']['sent']} получателей · {format_percent(impact['reactivation']['conversion_percent'])}",
        ],
        [
            "Пополнения после реактивации",
            impact["reactivation"]["topup_label"],
            "после первого возвратного визита до конца месяца",
        ],
        [
            "Кейс → пополнение",
            impact["cases_to_topup"]["topped_up_users"],
            f"из {impact['cases_to_topup']['case_users']} участников · {format_percent(impact['cases_to_topup']['conversion_percent'])}",
        ],
        ["Пополнения участников кейсов", impact["cases_to_topup"]["topup_label"], "в отчётном месяце"],
        [
            "Частота визитов вовлечённых",
            f"{format_number(freq['previous'], 2)} → {format_number(freq['current'], 2)}",
            f"изменение {format_percent(freq['change_percent'])}; корреляционный показатель",
        ],
    ]
    story.append(_data_table(["Результат", "Значение", "Как читать"], impact_rows, [70 * mm, 40 * mm, 65 * mm], styles))
    story += [
        Spacer(1, 14 * mm),
        Paragraph("Методика", styles["h1"]),
        Paragraph(
            "Визит — последовательность завершённых игровых сессий одного гостя с перерывом не более двух часов. Все периоды считаются в часовом поясе клуба. Денежные показатели включают положительные пополнения в пределах защитного лимита системы. Отчёт сохраняет снимок расчёта на дату формирования.",
            styles["body"],
        ),
    ]

    doc.build(story)
    return output
