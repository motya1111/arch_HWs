"""Render the C4 views as SVG and self-contained PlantUML using only Python stdlib."""

from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
BLUE = "#174a78"
STORE = "#38698f"
EXTERNAL = "#596373"
INK = "#183449"
ASYNC = "#a75a00"

SERVICES = [
    ("users", "Users Service", "Python / FastAPI", ["Учётные записи, роли, контакты", "и выбранные категории интересов"], ["Профили, роли, контакты", "и предпочтения"]),
    ("catalog", "Catalog Service", "Python / FastAPI", ["Предложения, цены, остатки", "и резервирование товаров"], ["Товары, предложения, цены", "остатки и резервы"]),
    ("feed", "Feed Service", "Python / FastAPI", ["Персональная лента, просмотры", "и проекция опубликованных товаров"], ["Просмотры, популярность", "проекции каталога и интересов"]),
    ("orders", "Orders Service", "Python 3.12 / HTTP", ["Заказы, расчёт суммы", "и координация оформления"], ["Заказы, снимки позиций", "суммы и состояние процесса"]),
    ("payments", "Payments Service", "Python / FastAPI", ["Платежи, учёт операций", "возвраты и интеграция с PSP"], ["Попытки платежа, суммы", "журнал операций и возвраты"]),
    ("notifications", "Notifications Service", "Python / FastAPI", ["Уведомления о заказах", "и повторные попытки отправки"], ["Задания, результаты доставки", "проекция проверенных контактов"]),
]

SYNC = [
    ("buyer", "web", "HTTPS: интерфейс покупателя"),
    ("seller", "web", "HTTPS: интерфейс продавца"),
    ("web", "gateway", "HTTPS/JSON: запросы интерфейса"),
    ("gateway", "users", "HTTPS/JSON: вход, профиль, проверка токена"),
    ("gateway", "catalog", "HTTPS/JSON: чтение и управление каталогом"),
    ("gateway", "feed", "HTTPS/JSON: лента и просмотры"),
    ("gateway", "orders", "HTTPS/JSON: оформление, состояние, отмена"),
    ("orders", "catalog", "HTTPS/JSON: reserve, confirm, release"),
    ("orders", "payments", "HTTPS/JSON: create, status, cancel, refund"),
    ("payments", "psp", "HTTPS API: платёж, сверка, отмена, возврат"),
    ("psp", "payments", "HTTPS webhook: проверяемый результат платежа"),
    ("notifications", "provider", "HTTPS API: отправка email/SMS"),
]

EVENTS = [
    ("users", "feed", "PreferencesUpdated / удаление профиля"),
    ("catalog", "feed", "CatalogUpdated"),
    ("users", "notifications", "UserContactsUpdated / удаление профиля"),
    ("payments", "orders", "PaymentStatusChanged"),
    ("orders", "notifications", "OrderStatusChanged"),
]


class SVG:
    def __init__(self, width, height, title):
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(title)}</title>',
            '<desc id="desc">C4 Container архитектура маркетплейса. Приватная база данных для каждого доменного сервиса. Сплошные связи синхронные, пунктирные — события через RabbitMQ.</desc>',
            '<defs><marker id="sync" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="#174a78"/></marker><marker id="async" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="#a75a00"/></marker></defs>',
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        ]

    def text(self, x, y, lines, size=18, color=INK, anchor="middle", bold=False, line_height=None, halo=False):
        if isinstance(lines, str):
            lines = [lines]
        step = line_height or size + 8
        weight = ' font-weight="700"' if bold else ""
        outline = ' stroke="#f6f9fc" stroke-width="5" stroke-linejoin="round" paint-order="stroke"' if halo else ""
        for index, line in enumerate(lines):
            self.parts.append(f'<text x="{x}" y="{y + index * step}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" fill="{color}" text-anchor="{anchor}"{weight}{outline}>{escape(line)}</text>')

    def boundary(self, x, y, width, height, label_x=None, label_y=None):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" fill="#f6f9fc" stroke="#748b9c" stroke-width="2" stroke-dasharray="10 6"/>')
        self.text(label_x or x + 24, label_y or y + 34, "Marketplace [Software System]", 23, anchor="start", bold=True)

    def box(self, x, y, width, height, name, kind, description, fill=BLUE):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" fill="{fill}" stroke="#ffffff" stroke-width="2"/>')
        self.text(x + width / 2, y + 35, name, 23, "#ffffff", bold=True)
        self.text(x + width / 2, y + 65, kind, 15, "#e8f0f8")
        self.text(x + width / 2, y + 99, description, 17, "#ffffff", line_height=25)

    def database(self, x, y, width, name, description):
        self.parts.append(f'<path d="M{x} {y + 18} C{x} {y - 6} {x + width} {y - 6} {x + width} {y + 18} L{x + width} {y + 145} C{x + width} {y + 169} {x} {y + 169} {x} {y + 145} Z" fill="{STORE}"/>')
        self.parts.append(f'<ellipse cx="{x + width / 2}" cy="{y + 18}" rx="{width / 2}" ry="18" fill="#4b7fa7"/>')
        self.text(x + width / 2, y + 56, name, 22, "#ffffff", bold=True)
        self.text(x + width / 2, y + 84, "[Container: Database | PostgreSQL]", 14, "#e8f0f8")
        self.text(x + width / 2, y + 114, description, 16, "#ffffff", line_height=24)

    def arrow(self, points, label=None, label_x=None, label_y=None, asynchronous=False, anchor="middle"):
        color = ASYNC if asynchronous else BLUE
        marker = "async" if asynchronous else "sync"
        dash = ' stroke-dasharray="9 6"' if asynchronous else ""
        coords = " ".join(f"{x},{y}" for x, y in points)
        self.parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.3"{dash} marker-end="url(#{marker})"/>')
        if label is not None:
            self.text(label_x, label_y, label, 17, color, anchor=anchor, line_height=24, halo=True)

    def save(self, name):
        (DOCS / name).write_text("\n".join(self.parts + ["</svg>"]) + "\n", encoding="utf-8")


def main_view():
    s = SVG(2360, 1590, "Marketplace — C4 Container: приложения, данные и синхронные API")
    s.text(45, 47, "Marketplace · C4 Container", 31, anchor="start", bold=True)
    s.text(45, 78, "Целевая архитектура. Реализован только health-check Orders Service.", 19, anchor="start")
    s.box(60, 110, 340, 125, "Покупатель", "[Person]", ["Лента и оформление заказов"], EXTERNAL)
    s.box(470, 110, 340, 125, "Продавец", "[Person]", ["Управление предложениями"], EXTERNAL)
    s.box(1560, 110, 380, 125, "Платёжный провайдер", "[External Software System]", ["Приём оплаты и возвраты"], EXTERNAL)
    s.box(1990, 110, 330, 125, "Email / SMS провайдер", "[External Software System]", ["Доставка сообщений"], EXTERNAL)
    s.boundary(40, 285, 2280, 1225, label_x=420, label_y=308)
    s.box(880, 355, 600, 140, "Web App", "[Container | React / TypeScript]", ["Интерфейс покупателя и продавца"])
    s.box(880, 585, 600, 140, "API Gateway", "[Container | NGINX]", ["TLS, маршрутизация, проверка токена через Users"])
    for index, (_, name, tech, description, data) in enumerate(SERVICES):
        x = 65 + index * 380
        s.box(x, 870, 330, 175, name, f"[Container | {tech}]", description)
        s.database(x, 1230, 330, name.split()[0] + " DB", data)
    s.arrow([(230, 235), (230, 340), (1000, 340), (1000, 355)], "HTTPS · интерфейс покупателя", 525, 332)
    s.arrow([(640, 235), (640, 262), (1300, 262), (1300, 355)], "HTTPS · интерфейс продавца", 1000, 253)
    s.arrow([(1180, 495), (1180, 585)], "HTTPS/JSON · запросы интерфейса", 1200, 544, anchor="start")
    s.arrow([(1030, 725), (1030, 765), (230, 765), (230, 870)], "HTTPS/JSON · вход, профиль, проверка токена", 605, 756)
    s.arrow([(1110, 725), (1110, 810), (610, 810), (610, 870)], "HTTPS/JSON · каталог", 695, 802)
    s.arrow([(990, 725), (990, 870)], ["HTTPS/JSON", "лента, просмотры"], 1005, 830, anchor="start")
    s.arrow([(1370, 725), (1370, 870)], ["HTTPS/JSON", "заказы, отмена"], 1385, 830, anchor="start")
    s.arrow([(1490, 870), (1490, 807), (1750, 807), (1750, 870)], ["HTTPS/JSON", "платёж: create / status / cancel / refund"], 1760, 779)
    s.arrow([(1280, 1045), (1280, 1120), (720, 1120), (720, 1045)], "HTTPS/JSON · резерв / подтверждение / освобождение", 1040, 1107)
    s.arrow([(1690, 870), (1690, 235)], ["HTTPS API", "платёж, сверка", "отмена, возврат"], 1670, 495, anchor="end")
    s.arrow([(1810, 235), (1810, 870)], ["HTTPS webhook", "результат оплаты", "проверяет Payments"], 1830, 620, anchor="start")
    s.arrow([(2150, 870), (2150, 235)], ["HTTPS API", "отправка email/SMS"], 2165, 495, anchor="start")
    for index in range(6):
        center = 230 + index * 380
        s.arrow([(center, 1045), (center, 1230)], ["SQL", "PostgreSQL protocol"], center + 12, 1180, anchor="start")
    s.text(75, 1435, "Каждое хранилище доступно только своему сервису. Общих таблиц и межсервисных SQL-запросов нет.", 20, anchor="start", bold=True)
    s.text(75, 1471, "Асинхронные связи (пунктир, via RabbitMQ / AMQP 0-9-1) показаны на отдельном C4 Container view: c4-events.svg.", 19, anchor="start", color=ASYNC)
    s.text(45, 1545, "Легенда: синий — приложение; цилиндр — приватная БД; серый — человек / внешняя система; сплошная стрелка — синхронный запрос.", 18, anchor="start")
    s.save("c4-container.svg")


def event_view():
    s = SVG(1840, 1210, "Marketplace — C4 Container: асинхронные взаимодействия")
    s.text(45, 50, "Marketplace · C4 Container · события", 30, anchor="start", bold=True)
    s.text(45, 85, "Дополнительный вид той же системы: только производители и потребители событий. БД и API показаны на основном виде.", 18, anchor="start")
    s.boundary(35, 130, 1770, 1000)
    positions = {"users": (710, 230), "catalog": (100, 530), "feed": (1310, 230), "orders": (1310, 860), "payments": (100, 860), "notifications": (840, 530)}
    for key, name, tech, description, _ in SERVICES:
        x, y = positions[key]
        s.box(x, y, 390, 170, name, f"[Container | {tech}]", description)
    s.arrow([(1100, 315), (1310, 315)], ["PreferencesUpdated", "AMQP via RabbitMQ"], 1205, 272, asynchronous=True)
    s.arrow([(295, 530), (295, 448), (1505, 448), (1505, 400)], ["CatalogUpdated · карточки, цены, доступность", "AMQP 0-9-1 via RabbitMQ"], 675, 437, asynchronous=True)
    s.arrow([(935, 400), (935, 530)], ["UserContactsUpdated", "AMQP via RabbitMQ"], 952, 486, asynchronous=True, anchor="start")
    s.arrow([(490, 945), (1310, 945)], ["PaymentStatusChanged · оплата / возврат", "AMQP 0-9-1 via RabbitMQ"], 870, 904, asynchronous=True)
    s.arrow([(1505, 860), (1505, 615), (1230, 615)], ["OrderStatusChanged", "AMQP via RabbitMQ"], 1525, 769, asynchronous=True, anchor="start")
    s.text(75, 1080, "Удаление профиля передаётся в оба потока Users: Feed и Notifications очищают свои проекции.", 18, anchor="start")
    s.text(45, 1174, "Пунктирная стрелка — логический поток события от производителя к потребителю. Очереди долговечные, доставка at least once.", 18, anchor="start", color=ASYNC)
    s.save("c4-events.svg")


def plantuml():
    lines = [
        "@startuml marketplace-container",
        "' Self-contained C4 notation; no remote includes or external icon libraries.",
        "title Marketplace — C4 Container (целевая архитектура)",
        "left to right direction",
        "skinparam shadowing false",
        "skinparam roundcorner 12",
        "skinparam defaultFontName SansSerif",
        "skinparam defaultFontSize 12",
        "skinparam rectangle {",
        "  BackgroundColor<<Container>> #174A78",
        "  FontColor<<Container>> white",
        "  BackgroundColor<<External>> #596373",
        "  FontColor<<External>> white",
        "}",
        "skinparam database {",
        "  FontColor white",
        "  BorderColor white",
        "}",
        'actor "Покупатель\\n[Person]\\nЛента и заказы" as buyer',
        'actor "Продавец\\n[Person]\\nУправление предложениями" as seller',
        'rectangle "Платёжный провайдер\\n[External Software System]\\nПриём оплаты и возвраты" as psp <<External>>',
        'rectangle "Email / SMS провайдер\\n[External Software System]\\nДоставка сообщений" as provider <<External>>',
        'rectangle "Marketplace [Software System]" {',
        'rectangle "Web App\\n[Container | React / TypeScript]\\nИнтерфейс покупателя и продавца" as web <<Container>>',
        'rectangle "API Gateway\\n[Container | NGINX]\\nTLS, маршрутизация, проверка токена через Users" as gateway <<Container>>',
    ]
    for key, name, tech, desc, data in SERVICES:
        description = "\\n".join(desc)
        contents = "\\n".join(data)
        lines.append(f'rectangle "{name}\\n[Container | {tech}]\\n{description}" as {key} <<Container>>')
        lines.append(f'database "{name.split()[0]} DB\\n[Container: Database | PostgreSQL]\\n{contents}" as {key}_db #38698F')
    lines.append("}")
    for source, target, label in SYNC:
        lines.append(f'{source} --> {target} : {label}')
    for key, *_ in SERVICES:
        lines.append(f'{key} --> {key}_db : SQL / PostgreSQL protocol: своё состояние')
    for source, target, event in EVENTS:
        lines.append(f'{source} -[#A75A00,dashed]-> {target} : {event}\\nAMQP 0-9-1 via RabbitMQ')
    lines += [
        "legend bottom",
        "  Синий = приложение, database = приватное хранилище",
        "  Серый = внешняя система, actor = человек",
        "  Сплошная стрелка = синхронный запрос",
        "  Пунктирная стрелка = асинхронное событие через RabbitMQ",
        "  Реализован только /health в Orders Service. Остальное — проект.",
        "endlegend",
        "@enduml",
    ]
    (DOCS / "c4-container.puml").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    DOCS.mkdir(parents=True, exist_ok=True)
    main_view()
    event_view()
    plantuml()
    print("Generated docs/c4-container.svg, docs/c4-events.svg, docs/c4-container.puml")
