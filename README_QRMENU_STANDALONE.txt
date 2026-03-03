QR Menu Standalone - فقط اپ business_menu + accounts (بدون loyalty و bonus)

نحوه اجرا:
1. محتویات این پوشه را در یک پوشه پروژه جدید بریزید (مثلاً qrmenu).
2. مجازی‌ساز: python -m venv venv و فعال‌سازی آن
3. نصب وابستگی: pip install -r requirements.txt
4. مایگریشن: python manage.py migrate
5. اجرا: python manage.py runserver

APIها تحت /api/business-menu/ و /business-menu/ هستند.
ادمین: /admin/
