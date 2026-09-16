from __future__ import annotations

import asyncio
import json
import logging
import secrets

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery

from .config import Settings
from .db import StoreDB
from .provider import ProviderClient, ProviderError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bonyan-store")
router = Router()
settings = Settings()
db = StoreDB(settings.database_path)
provider = ProviderClient(settings.api_base, settings.vente_reseller_key)

SUPPORT_URL = "https://t.me/BYN_SW"
TOPUP_TEXT = """✨ طرق شحن الرصيد ✨
━━━━━━━━━━━━━
🟡 Binance Pay (بينانس)
🆔 ID: 987503539
📱 المحافظ الإلكترونية (جيب، جوالي، ون كاش)
👤 الاسم: أحمد محمد عبد الله قحطان
🔢 الرقم: 779460213

🏦 بنك الكريمي الإسلامي
👤 الاسم: أحمد محمد عبد الله قحطان
🇾🇪 يمني: 3121836296
🇸🇦 سعودي: 3121784048

━━━━━━━━━━━━━
📩 بعد التحويل أرسل للدعم:
1️⃣ صورة أو رقم العملية.
2️⃣ المبلغ المحول.
3️⃣ الـ ID الخاص بحسابك في البوت.
⚡ يتم شحن رصيدك بعد التحقق."""


def welcome_text(user) -> str:
    return f"""💙 مرحبًا بك في
🛒 متجر بنيان للبرمجيات | Bonyan Software

🛍️ نوفر لك:
✨ اشتراكات Gemini AI Pro
🛠️ أدوات البرمجة
🎁 خدمات مواقع التواصل
💎 شحن الرصيد
🎧 دعم فني سريع

🆔 رقم حسابك: {user.id}
👤 اسم المستخدم: @{user.username if user.username else 'غير محدد'}"""


def money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_id_set


def products_keyboard(rows) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=f"{r['name']} — {money(round(float(r['sale_price_usd'] or r['price_usd']) * 100))}", callback_data=f"product:{r['id']}")] for r in rows]
    return InlineKeyboardMarkup(inline_keyboard=buttons or [[InlineKeyboardButton(text="لا توجد خدمات متاحة", callback_data="noop")]])


def product_keyboard(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="عرض السعر والشراء", callback_data=f"buy:{product_id}")], [InlineKeyboardButton(text="رجوع", callback_data="catalog")]])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="الإحصائيات", callback_data="admin:stats"), InlineKeyboardButton(text="الرصيد الرئيسي", callback_data="admin:wallet")],
        [InlineKeyboardButton(text="آخر الطلبات", callback_data="admin:orders"), InlineKeyboardButton(text="العملاء", callback_data="admin:users")],
        [InlineKeyboardButton(text="الخدمات والأسعار", callback_data="admin:products")],
    ])


@router.message(CommandStart())
async def start(message: Message) -> None:
    await db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(welcome_text(message.from_user), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 الخدمات", callback_data="catalog"), InlineKeyboardButton(text="💰 محفظتي", callback_data="balance")],
        [InlineKeyboardButton(text="💳 طرق شحن الرصيد", callback_data="topup_info")],
        [InlineKeyboardButton(text="📦 طلباتي", callback_data="orders"), InlineKeyboardButton(text="🎧 الدعم الفني", url=SUPPORT_URL)],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ]))


@router.message(Command("catalog"))
async def catalog_command(message: Message) -> None:
    await show_catalog(message)


async def show_catalog(target: Message | CallbackQuery) -> None:
    try:
        products, _ = await provider.products(settings.catalog_lang)
        if products:
            await db.replace_products(products)
    except ProviderError as exc:
        log.warning("catalog refresh failed: %s", exc.code)
    rows = await db.products()
    text = "الخدمات المتاحة:\n\n" + "\n".join(f"• {r['name']} — {money(round(float(r['sale_price_usd'] or r['price_usd']) * 100))}" for r in rows)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text or "لا توجد خدمات حاليًا", reply_markup=products_keyboard(rows))
        await target.answer()
    else:
        await target.answer(text or "لا توجد خدمات حاليًا", reply_markup=products_keyboard(rows))


@router.callback_query(F.data == "catalog")
async def catalog_callback(query: CallbackQuery) -> None:
    await show_catalog(query)


@router.callback_query(F.data == "topup_info")
async def topup_info_callback(query: CallbackQuery) -> None:
    await query.message.answer(TOPUP_TEXT, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎧 إرسال إثبات للدعم", url=SUPPORT_URL)], [InlineKeyboardButton(text="رجوع", callback_data="home")]]))
    await query.answer()


@router.callback_query(F.data == "lang:en")
async def language_english_callback(query: CallbackQuery) -> None:
    await db.set_language(query.from_user.id, "en")
    await query.message.answer(f"💙 Welcome to\n🛒 Bonyan Software Market\n\n🆔 Your account ID: {query.from_user.id}\n\nUse the buttons below to browse services, view your wallet, or contact support.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Services", callback_data="catalog"), InlineKeyboardButton(text="💰 My wallet", callback_data="balance")],
        [InlineKeyboardButton(text="💳 Top-up instructions", callback_data="topup_info")],
        [InlineKeyboardButton(text="📦 My orders", callback_data="orders"), InlineKeyboardButton(text="🎧 Support", url=SUPPORT_URL)],
        [InlineKeyboardButton(text="🇸🇦 العربية", callback_data="lang:ar")],
    ]))
    await query.answer()


@router.callback_query(F.data == "lang:ar")
async def language_arabic_callback(query: CallbackQuery) -> None:
    await db.set_language(query.from_user.id, "ar")
    await query.message.answer(welcome_text(query.from_user), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 الخدمات", callback_data="catalog"), InlineKeyboardButton(text="💰 محفظتي", callback_data="balance")],
        [InlineKeyboardButton(text="💳 طرق شحن الرصيد", callback_data="topup_info")],
        [InlineKeyboardButton(text="📦 طلباتي", callback_data="orders"), InlineKeyboardButton(text="🎧 الدعم الفني", url=SUPPORT_URL)],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ]))
    await query.answer()


@router.callback_query(F.data == "home")
async def home_callback(query: CallbackQuery) -> None:
    await query.message.answer(welcome_text(query.from_user))
    await query.answer()


@router.callback_query(F.data.startswith("product:"))
async def product_callback(query: CallbackQuery) -> None:
    product_id = int(query.data.split(":")[1])
    row = await db.product(product_id)
    if not row:
        await query.answer("الخدمة غير متاحة", show_alert=True)
        return
    sale = float(row["sale_price_usd"] or row["price_usd"])
    text = f"{row['name']}\n\n{row['description'] or 'خدمة رقمية'}\nسعر البيع: ${sale:.2f}\nنوع التسليم: {row['delivery_type']}"
    await query.message.edit_text(text, reply_markup=product_keyboard(product_id))
    await query.answer()


@router.callback_query(F.data.startswith("buy:"))
async def buy_callback(query: CallbackQuery) -> None:
    product_id = int(query.data.split(":")[1])
    row = await db.product(product_id)
    if not row:
        await query.answer("الخدمة غير متاحة", show_alert=True)
        return
    try:
        quote = await provider.quote(product_id, 1)
        provider_total = float(quote["quote"]["total"])
        sale_total = float(row["sale_price_usd"] or row["price_usd"])
        balance = await db.wallet_balance_cents(query.from_user.id)
        text = f"سعر المزود: ${provider_total:.2f}\nسعر البيع: ${sale_total:.2f}\nرصيدك: {money(balance)}\n\nالهامش التقريبي: ${sale_total - provider_total:.2f}"
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="شراء من رصيدي", callback_data=f"confirm:{product_id}")], [InlineKeyboardButton(text="إلغاء", callback_data="catalog")]])
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer()
    except (ProviderError, KeyError) as exc:
        await query.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_callback(query: CallbackQuery) -> None:
    if not settings.enable_wallet_purchase:
        await query.answer("الشراء من المحفظة غير مفعّل حتى يتم ربط الدفع الحقيقي واختباره.", show_alert=True)
        return
    product_id = int(query.data.split(":")[1])
    local_id = None
    sale_cents = 0
    idem = f"tg-{query.from_user.id}-{secrets.token_urlsafe(18)}"
    reference = f"telegram_user_{query.from_user.id}"
    try:
        row = await db.product(product_id)
        quote = await provider.quote(product_id, 1)
        provider_total = float(quote["quote"]["total"])
        sale_total = float(row["sale_price_usd"] or row["price_usd"])
        sale_cents = round(sale_total * 100)
        await db.debit_wallet(query.from_user.id, sale_cents, f"order:{idem}", f"Purchase {row['name']}")
        local_id = await db.create_order(query.from_user.id, product_id, 1, sale_total, provider_total, reference, idem)
        result = await provider.create_order(product_id, 1, reference, idem)
        order = result.get("order", {})
        provider_id = int(order["id"])
        status = order.get("status", "PAID_PENDING_DELIVERY")
        await db.update_provider_order(local_id, provider_id, status, json.dumps(result, ensure_ascii=False))
        await query.message.edit_text(f"تم إنشاء الطلب #{local_id}.\nالحالة: {status}\nاستخدم /status {local_id} للمتابعة.")
        await query.answer()
    except ValueError as exc:
        message = "الرصيد غير كافٍ." if str(exc) == "INSUFFICIENT_BALANCE" else "الحساب غير متاح للشراء."
        await query.answer(message, show_alert=True)
    except (ProviderError, KeyError, TypeError, ValueError) as exc:
        if sale_cents:
            await db.refund_wallet(query.from_user.id, sale_cents, f"refund:{idem}", "Provider order failed")
        log.warning("wallet order failed local=%s: %s", local_id, exc)
        await query.answer("فشل طلب المزود، وتمت إعادة الرصيد إلى محفظتك.", show_alert=True)


@router.callback_query(F.data == "balance")
async def balance_callback(query: CallbackQuery) -> None:
    balance = await db.wallet_balance_cents(query.from_user.id)
    await query.message.answer(f"رصيد محفظتك: {money(balance)}\n\nللشحن تواصل مع الإدارة أو استخدم مزود الدفع عند تفعيله.")
    await query.answer()


@router.message(Command("balance"))
async def balance_command(message: Message) -> None:
    await db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(f"رصيد محفظتك: {money(await db.wallet_balance_cents(message.from_user.id))}")


@router.message(Command("topup"))
async def topup_command(message: Message) -> None:
    if not settings.payment_provider_token:
        await message.answer("الشحن الإلكتروني غير مفعّل حاليًا. تواصل مع الإدارة للشحن اليدوي.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("استخدم: /topup المبلغ_بالدولار\nمثال: /topup 10")
        return
    try:
        amount = round(float(parts[1]), 2)
        cents = round(amount * 100)
        if cents < 100 or cents > 100000:
            raise ValueError
    except ValueError:
        await message.answer("المبلغ يجب أن يكون بين 1 و1000 دولار.")
        return
    payload = f"topup:{message.from_user.id}:{secrets.token_urlsafe(16)}"
    await message.answer_invoice(
        title="شحن محفظة ماركت بنيان",
        description=f"إضافة {amount:.2f} دولار إلى رصيدك الداخلي",
        payload=payload,
        provider_token=settings.payment_provider_token,
        currency="USD",
        prices=[LabeledPrice(label="رصيد المحفظة", amount=cents)],
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    if not query.invoice_payload.startswith(f"topup:{query.from_user.id}:") or query.currency != "USD":
        await query.answer(ok=False, error_message="بيانات الفاتورة غير صالحة.")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    if not payment or not payment.invoice_payload.startswith(f"topup:{message.from_user.id}:"):
        await message.answer("تعذر التحقق من عملية الدفع.")
        return
    reference = f"telegram-payment:{payment.telegram_payment_charge_id}"
    balance = await db.credit_wallet_once(message.from_user.id, payment.total_amount, reference, "Telegram payment top-up")
    await message.answer(f"تم تأكيد الدفع وإضافة {money(payment.total_amount)} إلى محفظتك. الرصيد الحالي: {money(balance)}")


@router.message(Command("orders"))
async def orders_command(message: Message) -> None:
    rows = await db.user_orders(message.from_user.id)
    await message.answer("لا توجد طلبات بعد." if not rows else "طلبـاتك:\n" + "\n".join(f"#{r['id']} — {r['product_name']} — {r['status']} — {money(round(float(r['amount_usd']) * 100))}" for r in rows))


@router.message(Command("status"))
async def status_command(message: Message) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("استخدم: /status رقم_الطلب")
        return
    row = await db.order(int(parts[1]))
    if not row or (row["telegram_user_id"] != message.from_user.id and not is_admin(message.from_user.id)):
        await message.answer("الطلب غير موجود.")
        return
    if row["provider_order_id"]:
        try:
            result = await provider.order(int(row["provider_order_id"]))
            order = result.get("order", {})
            await db.update_provider_order(row["id"], int(order["id"]), order.get("status", row["status"]), json.dumps(result, ensure_ascii=False))
            row = await db.order(row["id"])
        except ProviderError:
            pass
    await message.answer(f"الطلب #{row['id']}\nالخدمة: {row['product_name']}\nالحالة: {row['status']}\nالمبلغ: {money(round(float(row['amount_usd']) * 100))}")


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("هذا القسم للمشرفين فقط.")
        return
    await message.answer("لوحة تحكم ماركت بنيان", reply_markup=admin_keyboard())


@router.callback_query(F.data.startswith("admin:"))
async def admin_callback(query: CallbackQuery) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("غير مصرح", show_alert=True)
        return
    action = query.data.split(":", 1)[1]
    if action == "stats":
        s = await db.stats()
        await query.message.answer(f"الإحصائيات\nالعملاء: {s['users']}\nالطلبات: {s['orders']}\nإجمالي المبيعات: ${float(s['revenue']):.2f}\nالأرصدة المسجلة: {money(int(s['stored_cents']))}")
    elif action == "wallet":
        me = await provider.me()
        await query.message.answer(f"رصيد محفظة المزود: ${float(me.get('wallet_balance', 0)):.2f}")
    elif action == "orders":
        rows = await db.admin_orders()
        await query.message.answer("آخر الطلبات:\n" + ("\n".join(f"#{r['id']} user:{r['telegram_user_id']} {r['product_name']} {r['status']} ${float(r['amount_usd']):.2f}" for r in rows) or "لا توجد طلبات"))
    elif action == "users":
        rows = await db.admin_users()
        await query.message.answer("العملاء:\n" + ("\n".join(f"{r['telegram_id']} @{r['username'] or '-'} {money(int(r['balance_cents']))}" for r in rows) or "لا يوجد عملاء"))
    elif action == "products":
        rows = await db.products(False)
        await query.message.answer("الأسعار الحالية:\n" + ("\n".join(f"ID {r['id']} {r['name']}: تكلفة ${float(r['price_usd']):.2f} / بيع ${float(r['sale_price_usd'] or r['price_usd']):.2f}" for r in rows) or "لا توجد خدمات"))
    await query.answer()


@router.message(Command("admin_credit"))
async def admin_credit(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("غير مصرح")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("استخدم: /admin_credit telegram_user_id amount_usd")
        return
    try:
        user_id, amount = int(parts[1]), float(parts[2])
        balance = await db.credit_wallet(user_id, round(amount * 100), f"manual-credit:{message.from_user.id}", "Manual admin credit")
        await message.answer(f"تمت إضافة {amount:.2f} دولار. الرصيد الجديد: {money(balance)}")
    except (ValueError, TypeError):
        await message.answer("البيانات غير صحيحة")


@router.message(Command("admin_price"))
async def admin_price(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("غير مصرح")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("استخدم: /admin_price product_id sale_price_usd")
        return
    try:
        product_id, price = int(parts[1]), float(parts[2])
        if price < 0:
            raise ValueError
        ok = await db.set_sale_price(product_id, price)
        await message.answer("تم تحديث سعر البيع." if ok else "الخدمة غير موجودة.")
    except ValueError:
        await message.answer("البيانات غير صحيحة")


async def main() -> None:
    await db.init()
    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        me = await provider.me()
        log.info("provider authenticated; wallet balance is %.2f", float(me.get("wallet_balance", 0)))
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await provider.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
