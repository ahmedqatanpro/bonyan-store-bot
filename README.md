# Bonyan Services Store Bot

نسخة MVP آمنة لبوت متجر خدمات تلجرام متصل بـ VenteBot Reseller API الرسمي.

## المزايا الحالية

- قراءة هوية reseller ورصيد المحفظة.
- مزامنة الكتالوج العربي من `/api/reseller/products` مع ETag.
- عرض الخدمات والأسعار.
- حساب السعر عبر `/api/reseller/quote` قبل الشراء.
- إنشاء طلب idempotent عبر `/api/reseller/orders`.
- متابعة الطلب عبر `/api/reseller/orders/{id}`.
- دعم الخدمات التي تحتاج `activation_identifier` لاحقًا.
- محفظة عملاء بوحدة السنت، مع خصم ذري وإرجاع تلقائي عند فشل المزود.
- سعر بيع مستقل عن سعر المزود، ويمكن للمشرف تعديله عبر `/admin_price`.
- لوحة إدارة داخل Telegram عبر `/admin` لمراقبة الطلبات والعملاء ورصيد المزود.
- شحن يدوي للمحفظة عبر `/admin_credit` إلى حين ربط مزود الدفع.
- شحن إلكتروني اختياري عبر `/topup amount_usd` بعد وضع `PAYMENT_PROVIDER_TOKEN`.
- رسالة ترحيب باسم ماركت بنيان، رقم حساب العميل، زر دعم `@BYN_SW`، وتبديل عربي/English.
- تخزين محلي SQLite للطلبات والكتالوج.
- عدم وضع المفاتيح داخل الكود أو السجلات.
- احترام حد API وإعادة المحاولة الآمنة على 429 و5xx.

## التشغيل المحلي

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# ضع TELEGRAM_BOT_TOKEN ومفتاح VenteBot الجديد في .env فقط
python -m app.main
```

للتشغيل الحقيقي استخدم HTTPS/webhook أو عملية دائمة على استضافة مستمرة. النسخة الحالية تستخدم polling كبداية اختبارية. الدفع الإلكتروني غير مفعّل بعد؛ ربطه يجب أن يستخدم مزودًا معتمدًا ويتحقق من `successful_payment` قبل إضافة الرصيد. لا تضع `ENABLE_TEST_PURCHASE=true` أو `ENABLE_WALLET_PURCHASE=true` في الإنتاج قبل إكمال الدفع والاختبارات المالية.

## نموذج الربح والمحفظة

يحتفظ النظام بتكلفة المزود في `price_usd` وسعر البيع في `sale_price_usd`. السعر الافتراضي عند مزامنة خدمة جديدة هو تكلفة المزود × 1.30. ويمكن للمشرف تعديل السعر بالأمر `/admin_price product_id 1.50`. العميل لا يدفع مباشرة للمزود؛ يدفع من رصيده الداخلي، بينما يشتري النظام من محفظة reseller. ربح المتجر التقريبي هو سعر البيع ناقص تكلفة المزود ورسوم الدفع والاستردادات.

بيانات الشحن اليدوي تظهر من زر «طرق شحن الرصيد». بعد التحويل يرسل العميل الإثبات والمبلغ وTelegram ID إلى `@BYN_SW`، ثم يستخدم المشرف `/admin_credit telegram_user_id amount_usd` بعد التحقق.

الأرصدة تحفظ بالسنت وليس بأرقام عشرية. الشحن اليدوي للمشرف للاختبار فقط: `/admin_credit telegram_user_id amount_usd`. عند وضع `PAYMENT_PROVIDER_TOKEN` ينشئ `/topup 10` فاتورة بالدولار، ولا يضيف الرصيد إلا بعد التحقق من `successful_payment`. معرف عملية الدفع يستخدم كمرجع idempotent، لذلك لا يتكرر الشحن عند إعادة إرسال تحديث Telegram. تحقق من قواعد Telegram الحالية الخاصة بنوع المنتج والعملة قبل الإنتاج.

المشرف يستخدم `/admin`، ويجب وضع أرقام Telegram في `ADMIN_IDS` مفصولة بفواصل. أوامر الإدارة لا تعمل للمستخدم العادي.

## عقد VenteBot المعتمد

- المصادقة: `X-Reseller-Key`.
- الفحص والرصيد: `GET /api/reseller/me`.
- الكتالوج: `GET /api/reseller/products?lang=ar`.
- التسعير: `POST /api/reseller/quote` body `{product_id, quantity}`.
- إنشاء الطلب: `POST /api/reseller/orders` body `{product_id, quantity, activation_identifier?, customer_reference, idempotency_key}`.
- قراءة الطلب: `GET /api/reseller/orders/{order_id}`.
- تسليم معرّف التفعيل لاحقًا: `POST /api/reseller/orders/{order_id}/activation-identifier`.
- الحالات: `COMPLETED`, `PAID_PENDING_DELIVERY`, `AWAITING_ACTIVATION_INFO`, `AWAITING_ACTIVATION`, `CANCELLED`.
- حد الاستخدام: 60 طلبًا في 60 ثانية لكل مفتاح.

## ملاحظات الإنتاج

المفتاح الذي ظهر في محادثة أو سجل يجب إلغاؤه وإنشاء بديل. لا ترفع `.env` إلى Git. قبل تفعيل الدفع، أضف مزود دفع ودفتر حركات واستردادًا idempotent. لا تعرض `account_data` أو أي نتيجة حساسة إلا للمستخدم الذي يملك الطلب.
