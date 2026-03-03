فولدر اپ‌های گوگل پلی / Google Play Apps Folder
============================================

۳ اپ: QR Menu، Bonus، Bonus Panel

فایل‌های APK را اینجا بگذارید. نام‌های تطبیق‌داده‌شده در config/settings.py در APP_DOWNLOAD_APPS است.
Place your APK files here. Name mapping is in config/settings.py → APP_DOWNLOAD_APPS.

  - QR Menu:    MyQrBonus.apk, MyQrMenu.apk, QrMenu.apk, qr-menu.apk, qrmenu.apk, qr_menu.apk
  - Bonus:      Bonus-20260123-2104.apk, MyBonus.apk, bonus.apk, Bonus.apk
  - Bonus Panel: BonusPanel-release.apk, bonus-panel.apk, bonuspanel.apk

لینک iOS در "ios" و در صورت نیاز لینک اندروید در "android" (URL یا مسیر مثل apps/MyQrBonus.apk).
Add iOS (App Store) in "ios"; for Android you can set "android" (URL or path like apps/MyQrBonus.apk).

در production: python manage.py collectstatic

--- برای Scalingo (حجم آرشیو محدود ۳۰۰ مگ) ---
فایل‌های APK در .gitignore هستند. آن‌ها را روی CDN آپلود کنید و در APP_DOWNLOAD_APPS
فیلد "android" را با URL کامل پر کنید؛ مثلا "android": "https://cdn.example.com/MyQrBonus.apk"
For Scalingo: host APKs on CDN and set "android" in APP_DOWNLOAD_APPS to the full URL.
