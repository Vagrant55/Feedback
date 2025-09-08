import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from telegram import Bot


# === 🔐 НАСТРОЙКИ ===
# ✅ API URLs (убраны лишние пробелы в конце)
FEEDBACK_API = "https://feedbacks-api.wildberries.ru/api/v1/feedbacks"
CARDS_API = "https://suppliers-api.wildberries.ru/content/v2/get/cards/list"

# ✅ Рабочие токены (для безопасности лучше вынести в переменные окружения)
WILDBERRIES_FEEDBACK_TOKEN = (
    "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwNTIwdjEiLCJ0eXAiOiJKV1QifQ.eyJlbnQiOjEsImV4cCI6MTc3MTUzNDgxOCwiaWQiOiIwMTk4Y2JkYi04NzIwLTdhZjMtOGU4ZS05ZTIyZjhmMjZkMjMiLCJpaWQiOjQxNTAzMjgwLCJvaWQiOjU2NzEzMSwicyI6MTI4LCJzaWQiOiI4YTNhYmRjMS0wMTdkLTQzMTgtOTI4MC0wNmU3OWRjNzllZmUiLCJ0IjpmYWxzZSwidWlkIjo0MTUwMzI4MH0.dxXdZp8WIuTAwLmcDa9YYog79jz-6iAWYajM0cP3Ul1-rQ82ZksWjp8Gx6JQhG8wlvn6JVJB9Ty45dpeaq0b_g"
)
WILDBERRIES_CARDS_TOKEN = (
    "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwNTIwdjEiLCJ0eXAiOiJKV1QifQ.eyJlbnQiOjEsImV4cCI6MTc3MjA1MDQ3MSwiaWQiOiIwMTk4ZWE5Ny1jMjY0LTcxMjgtODU4MC0xOTdkNTJhYjIzYTgiLCJpaWQiOjE5ODUzNjk5LCJvaWQiOjI5MDk0NywicyI6MTA3Mzc0MTgyNiwic2lkIjoiNWZmZDIyZjgtMWYzMi00MjMyLTk4NTMtZDZmOTk5MWMwNDI1IiwidCI6ZmFsc2UsInVpZCI6MTk4NTM2OTl9.0qwunxjymXMVaCfcDcr0gOaPS70EMENHo52x9VvMnyEFtoNjRf5JYKlTdpd7YD2h2Ln7gDmlm-RLHVGbLxeiuA"
)
TELEGRAM_BOT_TOKEN = "8391873182:AAHUykid30Fssju6OfnUtwv6uCc9ZFdazho"
TELEGRAM_CHAT_ID = 935264202


def _safe_iso_to_datetime(value: Any) -> datetime:
    """Безопасно конвертирует разные форматы дат в datetime для сортировки."""
    if not value:
        return datetime.min
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    # Обрезаем микросекунды, Z и т.п.
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except Exception:
        # Популярные запасные форматы
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
    return datetime.min


def check_tokens() -> bool:
    """Проверяем наличие необходимых токенов."""
    missing_tokens: List[str] = []
    if not WILDBERRIES_FEEDBACK_TOKEN:
        missing_tokens.append("WB_FEEDBACK_TOKEN")
    if not WILDBERRIES_CARDS_TOKEN:
        missing_tokens.append("WB_CARDS_TOKEN")

    if missing_tokens:
        print("❌ ОТСУТСТВУЮТ ОБЯЗАТЕЛЬНЫЕ ТОКЕНЫ:")
        for token in missing_tokens:
            print(f"   • {token}")
        print("\n💡 Установите переменные окружения или введите токены вручную")
        return False

    print("✅ Токены загружены успешно")
    return True


def _extract_feedback_batch(data: Any) -> List[Dict[str, Any]]:
    """Извлекает массив отзывов из возможных структур ответа API."""
    if not isinstance(data, dict):
        return []
    if "feedbacks" in data and isinstance(data["feedbacks"], list):
        return data["feedbacks"]
    # Некоторые ответы приходят в data.feedbacks
    inner = data.get("data")
    if isinstance(inner, dict) and isinstance(inner.get("feedbacks"), list):
        return inner["feedbacks"]
    return []


def get_all_feedbacks(feedback_token: str) -> List[Dict[str, Any]]:
    print("🔍 Получаем все отзывы...")

    if not feedback_token:
        print("❌ Отсутствует токен для получения отзывов")
        return []

    # Попробуем разные варианты заголовков авторизации
    header_variants: List[Dict[str, str]] = [
        {"Authorization": feedback_token},
        {"Authorization": f"Bearer {feedback_token}"},
        {"X-Authorization": feedback_token},
        {"X-Authorization": f"Bearer {feedback_token}"},
    ]
    common_headers = {"Accept": "application/json"}
    feedbacks: List[Dict[str, Any]] = []

    # Первичная попытка для получения структуры
    param_variants: List[Dict[str, Any]] = [
        {"take": 100, "skip": 0},
        {"take": 100, "skip": 0, "order": "dateDesc"},
    ]

    success = False
    attempt = 0
    for headers in header_variants:
        merged_headers = {**common_headers, **headers}
        for params in param_variants:
            attempt += 1
            print(f"🔄 Попытка #{attempt} с заголовками {list(headers.keys())} и параметрами: {params}")
            try:
                response = requests.get(
                    FEEDBACK_API, headers=merged_headers, params=params, timeout=30
                )
                print(f"   Статус: {response.status_code}")
                if response.status_code != 200:
                    snippet = response.text[:300] if response.text else str(response.content[:300])
                    if response.status_code in (401, 403):
                        print("   ⛔ Доступ запрещен. Проверьте валидность и права токена.")
                    print(f"   Ответ: {snippet}")
                    continue

                data = response.json()
                batch = _extract_feedback_batch(data)
                if batch:
                    feedbacks.extend(batch[:100])
                    print(f"✅ Найдено отзывов: {len(batch)}")
                    success = True
                    break
                else:
                    print("   Отзывы не найдены в ожидаемых ключах")
                    print(
                        f"   Ключи ответа: {list(data) if isinstance(data, dict) else type(data)}"
                    )
            except Exception as e:
                print(f"   Исключение: {e}")
        if success:
            break

    if not success:
        print("❌ Все попытки неудачны")
        return []

    # Если получили первые 100, дотягиваем пагинацией
    if len(feedbacks) == 100:
        print("📄 Загружаем остальные отзывы...")
        skip = 100
        while True:
            params = {
                "take": 100,
                "skip": skip,
                "order": "dateDesc",
            }
            try:
                # Повторяем те же варианты заголовков, что и выше, пока не найдём рабочие
                resp = None
                for headers in header_variants:
                    merged_headers = {**common_headers, **headers}
                    resp = requests.get(
                        FEEDBACK_API, headers=merged_headers, params=params, timeout=30
                    )
                    if resp.status_code == 200:
                        break
                if resp.status_code != 200:
                    break
                data = resp.json()
                batch = _extract_feedback_batch(data)
                if not batch:
                    break
                feedbacks.extend(batch)
                print(f"📄 Всего загружено: {len(feedbacks)}", end="\r")
                if len(batch) < 100:
                    break
                skip += 100
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                break

    print(f"✅ Загружено {len(feedbacks)} отзывов")
    return feedbacks


def _normalize_article_from_feedback(feedback: Dict[str, Any]) -> Optional[str]:
    product_details = feedback.get("productDetails")
    candidates = []
    if isinstance(product_details, dict):
        candidates.extend(
            [
                product_details.get("supplierArticle"),
                product_details.get("nmId"),
                product_details.get("productId"),
                product_details.get("article"),
            ]
        )
    candidates.extend(
        [
            feedback.get("supplierArticle"),
            feedback.get("nmId"),
            feedback.get("productId"),
            feedback.get("article"),
        ]
    )
    for candidate in candidates:
        if candidate is not None and str(candidate).strip():
            return str(candidate)
    return None


def get_product_names(articles: List[str], cards_token: str) -> Dict[str, str]:
    if not articles:
        return {}

    print(f"📌 Получаем названия для {len(articles)} товаров...")

    if not cards_token:
        print("❌ Отсутствует токен для получения карточек")
        return {art: "Токен отсутствует" for art in articles}

    headers = {"Authorization": cards_token}
    payload: Dict[str, Any] = {
        "query": {
            "limit": 100,
            "filters": [
                {"column": "supplierArticle", "filter": articles, "operator": "IN"}
            ],
        }
    }

    try:
        response = requests.post(CARDS_API, json=payload, headers=headers, timeout=60)
        if response.status_code != 200:
            print("❌ Ошибка API карточек:", response.text[:200])
            return {art: "Ошибка API" for art in articles}

        data = response.json()
        cards = []
        if isinstance(data, dict):
            if isinstance(data.get("cards"), list):
                cards = data["cards"]
            elif isinstance(data.get("data"), dict) and isinstance(
                data["data"].get("cards"), list
            ):
                cards = data["data"]["cards"]

        result: Dict[str, str] = {}
        for card in cards:
            if not isinstance(card, dict):
                continue
            supplier_article = str(card.get("supplierArticle", "")).strip()
            title = card.get("title") or card.get("name") or "Без названия"
            if supplier_article:
                result[supplier_article] = title

        # Добавляем артикулы, для которых не найдены карточки
        for art in articles:
            if art not in result:
                result[art] = "Карточка не найдена"

        return result

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return {art: "Ошибка запроса" for art in articles}


def analyze_latest_reviews_per_product(
    feedbacks: List[Dict[str, Any]], article_to_name: Dict[str, str]
) -> List[Dict[str, Any]]:
    print("📊 Ищем по каждому товару до 5 самых свежих отзывов...")

    def _extract_rating(fb: Dict[str, Any]) -> Optional[int]:
        for key in ("productValuation", "rating", "valuation"):
            val = fb.get(key)
            if isinstance(val, (int, float)):
                try:
                    return int(val)
                except Exception:
                    continue
        return None

    def _extract_date(fb: Dict[str, Any]) -> datetime:
        for key in ("createdDate", "createdAt", "date"):
            if key in fb:
                return _safe_iso_to_datetime(fb.get(key))
        return datetime.min

    # Группируем отзывы по артикулу
    article_to_feedbacks: Dict[str, List[Dict[str, Any]]] = {}
    for fb in feedbacks:
        article = _normalize_article_from_feedback(fb)
        if not article:
            continue
        article_to_feedbacks.setdefault(article, []).append(fb)

    # Для каждого артикула берём до 5 свежих отзывов
    result: List[Dict[str, Any]] = []
    for article, fbs in article_to_feedbacks.items():
        fbs_sorted = sorted(fbs, key=_extract_date, reverse=True)
        top_n = fbs_sorted[:5]

        # Определяем название товара
        product_name = "Не найдено"
        # Пытаемся взять название из первого отзыва productDetails
        if top_n:
            pdict = top_n[0].get("productDetails")
            if isinstance(pdict, dict):
                product_name = pdict.get("productName", "Не найдено")
        if product_name == "Не найдено":
            product_name = article_to_name.get(article, "Не найдено")

        for idx, fb in enumerate(top_n, 1):
            rating = _extract_rating(fb)
            rating_display: Any = rating if rating is not None else "N/A"

            created_dt = _extract_date(fb)
            date_part = (
                created_dt.strftime("%Y-%m-%d") if created_dt != datetime.min else "N/A"
            )
            time_part = created_dt.strftime("%H:%M") if created_dt != datetime.min else ""

            raw_text = fb.get("text")
            text_str = str(raw_text) if raw_text is not None else "—"
            if len(text_str) > 300:
                text_str = text_str[:300] + "..."

            result.append(
                {
                    "Номер": idx,
                    "Название товара": product_name,
                    "Артикул": article,
                    "Дата отзыва": date_part,
                    "Время": time_part,
                    "Оценка": rating_display,
                    "Текст отзыва": text_str,
                }
            )

    print(
        f"✅ Сформирован список: товаров {len(article_to_feedbacks)}, записей {len(result)}"
    )
    return result


def create_excel(data: List[Dict[str, Any]]) -> Optional[str]:
    if not data:
        print("📭 Нет данных для отчёта")
        return None

    filename = f"WB_до5_свежих_по_каждому_{datetime.now().strftime('%d%m%Y_%H%M')}.xlsx"

    try:
        df = pd.DataFrame(data)
        # Попробуем сохранить с openpyxl, если нет — позволим pandas выбрать доступный движок
        try:
            df.to_excel(filename, index=False, engine="openpyxl")
        except Exception:
            df.to_excel(filename, index=False)
        print(f"✅ Файл создан: {filename}")
        return filename
    except Exception as e:
        print(f"❌ Ошибка создания Excel: {e}")
        return None


async def send_to_telegram(filename: Optional[str], count: int) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram токен или chat_id отсутствуют - пропускаем отправку")
        return

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        message = (
            f"🕑 По каждому товару отобрано до 5 свежих отзывов (всего записей: {count})"
            if count > 0
            else "📭 Свежих отзывов не найдено"
        )

        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        if filename:
            with open(filename, "rb") as file_obj:
                await bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=file_obj)
        print("✅ Отчёт отправлен в Telegram!")
    except Exception as e:
        print(f"❌ Ошибка отправки в Telegram: {e}")


def display_results(data: List[Dict[str, Any]]) -> None:
    if not data:
        print("\n🎉 ОТЛИЧНЫЕ НОВОСТИ!")
        print("📭 Плохих отзывов с оценкой < 5 не найдено!")
        print("✅ Все ваши клиенты довольны!")
        return

    print("\n" + "=" * 80)
    print("🕑  ДО 5 СВЕЖИХ ОТЗЫВОВ ПО КАЖДОМУ ТОВАРУ")
    print("=" * 80)

    for item in data:
        print(f"\n📍 #{item['Номер']} - {item['Дата отзыва']} {item['Время']}")
        print(f"🛍️  ТОВАР: {item['Название товара']}")
        print(f"📦 Артикул: {item['Артикул']}")
        print(f"⭐ ОЦЕНКА: {item['Оценка']}/5")
        print(f"💬 ОТЗЫВ: {item['Текст отзыва']}")
        print("-" * 60)


def main() -> None:
    print(f"📅 Запуск: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print("🔍 Парсер отзывов Wildberries - 5 самых свежих отзывов с оценкой < 5")
    print("-" * 60)

    # Используем встроенные токены
    feedback_token = WILDBERRIES_FEEDBACK_TOKEN
    cards_token = WILDBERRIES_CARDS_TOKEN

    if not check_tokens():
        return

    print("✅ Токены загружены, начинаем анализ...")

    # 1. Получаем все отзывы
    all_feedbacks = get_all_feedbacks(feedback_token)
    if not all_feedbacks:
        print("❌ Не удалось получить отзывы")
        return

    # 2. Собираем артикулы
    articles_set = set()
    for fb in all_feedbacks:
        article = _normalize_article_from_feedback(fb)
        if article:
            articles_set.add(article)

    articles = list(articles_set)
    print(f"📦 Найдено товаров: {len(articles)}")
    if articles:
        print(f"📋 Первые артикулы: {articles[:5]}")

    # 3. Названия (если есть артикулы)
    article_to_name = get_product_names(articles, cards_token) if articles else {}

    # 4. Анализ: до 5 самых свежих отзывов для каждого товара
    report_data = analyze_latest_reviews_per_product(all_feedbacks, article_to_name)

    # 5. Показываем результат в консоли
    display_results(report_data)

    # 6. Создаём Excel
    filename = create_excel(report_data)

    # 7. Отправка в Telegram (опционально)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        asyncio.run(send_to_telegram(filename, len(report_data)))


if __name__ == "__main__":
    main()

