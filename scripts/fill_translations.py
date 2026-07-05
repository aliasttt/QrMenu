"""
Fills locale/<lang>/LC_MESSAGES/django.po files with translations from a
built-in dictionary. Any msgid not found in the dictionary is left as empty
msgstr, which causes Django to fall back to the English source string.

Run:  python scripts/fill_translations.py
Then: python manage.py compilemessages
"""
from __future__ import annotations
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOCALE_DIR = BASE / "locale"

# Translation table: english source -> dict(lang -> translation)
# Only strings listed here get translated; anything else falls back to English.
# Order is not important. `\n` inside values is literal newline in the .po file.
T: dict[str, dict[str, str]] = {
    # ─── Navigation & common UI ────────────────────────────────────
    "Home": {
        "de": "Startseite", "es": "Inicio", "ar": "الرئيسية", "tr": "Ana Sayfa",
        "it": "Home", "fr": "Accueil", "ru": "Главная", "nl": "Home",
        "ja": "ホーム", "el": "Αρχική", "cs": "Domů", "zh_Hans": "首页",
        "pt": "Início", "ko": "홈", "pl": "Strona główna",
    },
    "Features": {
        "de": "Funktionen", "es": "Funciones", "ar": "الميزات", "tr": "Özellikler",
        "it": "Funzionalità", "fr": "Fonctionnalités", "ru": "Возможности",
        "nl": "Functies", "ja": "機能", "el": "Χαρακτηριστικά", "cs": "Funkce",
        "zh_Hans": "功能", "pt": "Recursos", "ko": "기능", "pl": "Funkcje",
    },
    "Services": {
        "de": "Dienstleistungen", "es": "Servicios", "ar": "الخدمات",
        "tr": "Hizmetler", "it": "Servizi", "fr": "Services", "ru": "Услуги",
        "nl": "Diensten", "ja": "サービス", "el": "Υπηρεσίες", "cs": "Služby",
        "zh_Hans": "服务", "pt": "Serviços", "ko": "서비스", "pl": "Usługi",
    },
    "How it works": {
        "de": "Wie es funktioniert", "es": "Cómo funciona", "ar": "كيف يعمل",
        "tr": "Nasıl çalışır", "it": "Come funziona", "fr": "Comment ça marche",
        "ru": "Как это работает", "nl": "Hoe het werkt", "ja": "使い方",
        "el": "Πώς λειτουργεί", "cs": "Jak to funguje", "zh_Hans": "如何运作",
        "pt": "Como funciona", "ko": "이용 방법", "pl": "Jak to działa",
    },
    "Pricing": {
        "de": "Preise", "es": "Precios", "ar": "الأسعار", "tr": "Fiyatlandırma",
        "it": "Prezzi", "fr": "Tarifs", "ru": "Цены", "nl": "Prijzen",
        "ja": "料金", "el": "Τιμολόγηση", "cs": "Ceník", "zh_Hans": "价格",
        "pt": "Preços", "ko": "요금제", "pl": "Cennik",
    },
    "Restaurants & Cafes": {
        "de": "Restaurants & Cafés", "es": "Restaurantes y cafés",
        "ar": "المطاعم والمقاهي", "tr": "Restoranlar ve Kafeler",
        "it": "Ristoranti e caffè", "fr": "Restaurants et cafés",
        "ru": "Рестораны и кафе", "nl": "Restaurants & cafés",
        "ja": "レストラン＆カフェ", "el": "Εστιατόρια & Καφέ",
        "cs": "Restaurace a kavárny", "zh_Hans": "餐厅与咖啡馆",
        "pt": "Restaurantes e cafés", "ko": "레스토랑 & 카페",
        "pl": "Restauracje i kawiarnie",
    },
    "Contact": {
        "de": "Kontakt", "es": "Contacto", "ar": "اتصل بنا", "tr": "İletişim",
        "it": "Contatti", "fr": "Contact", "ru": "Контакты", "nl": "Contact",
        "ja": "お問い合わせ", "el": "Επικοινωνία", "cs": "Kontakt",
        "zh_Hans": "联系我们", "pt": "Contato", "ko": "문의", "pl": "Kontakt",
    },
    "Login": {
        "de": "Anmelden", "es": "Iniciar sesión", "ar": "تسجيل الدخول",
        "tr": "Giriş", "it": "Accedi", "fr": "Connexion", "ru": "Войти",
        "nl": "Inloggen", "ja": "ログイン", "el": "Σύνδεση", "cs": "Přihlásit",
        "zh_Hans": "登录", "pt": "Entrar", "ko": "로그인", "pl": "Zaloguj",
    },
    "Logout": {
        "de": "Abmelden", "es": "Cerrar sesión", "ar": "تسجيل الخروج",
        "tr": "Çıkış", "it": "Esci", "fr": "Déconnexion", "ru": "Выйти",
        "nl": "Uitloggen", "ja": "ログアウト", "el": "Αποσύνδεση",
        "cs": "Odhlásit", "zh_Hans": "退出", "pt": "Sair", "ko": "로그아웃",
        "pl": "Wyloguj",
    },
    "Register": {
        "de": "Registrieren", "es": "Registrarse", "ar": "التسجيل",
        "tr": "Kayıt ol", "it": "Registrati", "fr": "S'inscrire",
        "ru": "Регистрация", "nl": "Registreren", "ja": "登録",
        "el": "Εγγραφή", "cs": "Registrace", "zh_Hans": "注册",
        "pt": "Registrar", "ko": "가입", "pl": "Zarejestruj",
    },
    "Get Started": {
        "de": "Loslegen", "es": "Empezar", "ar": "ابدأ الآن",
        "tr": "Başla", "it": "Inizia", "fr": "Commencer",
        "ru": "Начать", "nl": "Aan de slag", "ja": "始める",
        "el": "Ξεκινήστε", "cs": "Začít", "zh_Hans": "开始",
        "pt": "Começar", "ko": "시작하기", "pl": "Zaczynamy",
    },
    "Dashboard": {
        "de": "Dashboard", "es": "Panel", "ar": "لوحة التحكم",
        "tr": "Panel", "it": "Dashboard", "fr": "Tableau de bord",
        "ru": "Панель", "nl": "Dashboard", "ja": "ダッシュボード",
        "el": "Πίνακας", "cs": "Nástěnka", "zh_Hans": "仪表盘",
        "pt": "Painel", "ko": "대시보드", "pl": "Pulpit",
    },
    "Panel": {
        "de": "Panel", "es": "Panel", "ar": "لوحة", "tr": "Panel",
        "it": "Pannello", "fr": "Panneau", "ru": "Панель", "nl": "Paneel",
        "ja": "パネル", "el": "Πίνακας", "cs": "Panel", "zh_Hans": "面板",
        "pt": "Painel", "ko": "패널", "pl": "Panel",
    },
    "Settings": {
        "de": "Einstellungen", "es": "Ajustes", "ar": "الإعدادات",
        "tr": "Ayarlar", "it": "Impostazioni", "fr": "Paramètres",
        "ru": "Настройки", "nl": "Instellingen", "ja": "設定",
        "el": "Ρυθμίσεις", "cs": "Nastavení", "zh_Hans": "设置",
        "pt": "Configurações", "ko": "설정", "pl": "Ustawienia",
    },
    "Menu": {
        "de": "Menü", "es": "Menú", "ar": "القائمة", "tr": "Menü",
        "it": "Menu", "fr": "Menu", "ru": "Меню", "nl": "Menu",
        "ja": "メニュー", "el": "Μενού", "cs": "Menu", "zh_Hans": "菜单",
        "pt": "Menu", "ko": "메뉴", "pl": "Menu",
    },
    "QR Menu": {
        "de": "QR-Menü", "es": "Menú QR", "ar": "قائمة QR", "tr": "QR Menü",
        "it": "Menu QR", "fr": "Menu QR", "ru": "QR-меню", "nl": "QR-menu",
        "ja": "QRメニュー", "el": "QR Μενού", "cs": "QR menu",
        "zh_Hans": "二维码菜单", "pt": "Menu QR", "ko": "QR 메뉴",
        "pl": "Menu QR",
    },
    "Categories": {
        "de": "Kategorien", "es": "Categorías", "ar": "الفئات",
        "tr": "Kategoriler", "it": "Categorie", "fr": "Catégories",
        "ru": "Категории", "nl": "Categorieën", "ja": "カテゴリー",
        "el": "Κατηγορίες", "cs": "Kategorie", "zh_Hans": "分类",
        "pt": "Categorias", "ko": "카테고리", "pl": "Kategorie",
    },
    "Menu Items": {
        "de": "Menü-Artikel", "es": "Elementos del menú",
        "ar": "عناصر القائمة", "tr": "Menü öğeleri", "it": "Voci menu",
        "fr": "Éléments du menu", "ru": "Пункты меню",
        "nl": "Menu-items", "ja": "メニュー項目", "el": "Στοιχεία μενού",
        "cs": "Položky menu", "zh_Hans": "菜单项", "pt": "Itens do menu",
        "ko": "메뉴 항목", "pl": "Pozycje menu",
    },
    "Campaigns": {
        "de": "Kampagnen", "es": "Campañas", "ar": "الحملات",
        "tr": "Kampanyalar", "it": "Campagne", "fr": "Campagnes",
        "ru": "Кампании", "nl": "Campagnes", "ja": "キャンペーン",
        "el": "Εκστρατείες", "cs": "Kampaně", "zh_Hans": "活动",
        "pt": "Campanhas", "ko": "캠페인", "pl": "Kampanie",
    },
    "Language": {
        "de": "Sprache", "es": "Idioma", "ar": "اللغة", "tr": "Dil",
        "it": "Lingua", "fr": "Langue", "ru": "Язык", "nl": "Taal",
        "ja": "言語", "el": "Γλώσσα", "cs": "Jazyk", "zh_Hans": "语言",
        "pt": "Idioma", "ko": "언어", "pl": "Język",
    },
    "Skip to main content": {
        "de": "Zum Hauptinhalt springen", "es": "Ir al contenido principal",
        "ar": "الانتقال إلى المحتوى الرئيسي", "tr": "Ana içeriğe atla",
        "it": "Vai al contenuto principale", "fr": "Aller au contenu principal",
        "ru": "Перейти к основному содержанию", "nl": "Naar hoofdinhoud",
        "ja": "メインコンテンツへスキップ", "el": "Μετάβαση στο κύριο περιεχόμενο",
        "cs": "Přeskočit na hlavní obsah", "zh_Hans": "跳到主要内容",
        "pt": "Ir para o conteúdo principal", "ko": "본문으로 건너뛰기",
        "pl": "Przejdź do treści głównej",
    },
    "Change language": {
        "de": "Sprache ändern", "es": "Cambiar idioma", "ar": "تغيير اللغة",
        "tr": "Dili değiştir", "it": "Cambia lingua", "fr": "Changer de langue",
        "ru": "Сменить язык", "nl": "Taal wijzigen", "ja": "言語を変更",
        "el": "Αλλαγή γλώσσας", "cs": "Změnit jazyk", "zh_Hans": "更改语言",
        "pt": "Alterar idioma", "ko": "언어 변경", "pl": "Zmień język",
    },
    "Toggle dark mode": {
        "de": "Dunkelmodus umschalten", "es": "Alternar modo oscuro",
        "ar": "تبديل الوضع الداكن", "tr": "Karanlık modu değiştir",
        "it": "Alterna modalità scura", "fr": "Basculer le mode sombre",
        "ru": "Переключить тёмный режим", "nl": "Donkere modus wisselen",
        "ja": "ダークモード切替", "el": "Εναλλαγή σκοτεινής λειτουργίας",
        "cs": "Přepnout tmavý režim", "zh_Hans": "切换深色模式",
        "pt": "Alternar modo escuro", "ko": "다크 모드 전환",
        "pl": "Przełącz tryb ciemny",
    },
    "Toggle menu": {
        "de": "Menü umschalten", "es": "Alternar menú", "ar": "تبديل القائمة",
        "tr": "Menüyü değiştir", "it": "Alterna menu", "fr": "Basculer le menu",
        "ru": "Переключить меню", "nl": "Menu wisselen", "ja": "メニュー切替",
        "el": "Εναλλαγή μενού", "cs": "Přepnout menu", "zh_Hans": "切换菜单",
        "pt": "Alternar menu", "ko": "메뉴 전환", "pl": "Przełącz menu",
    },
    "Hello, %(name)s": {
        "de": "Hallo, %(name)s", "es": "Hola, %(name)s", "ar": "مرحباً، %(name)s",
        "tr": "Merhaba, %(name)s", "it": "Ciao, %(name)s", "fr": "Bonjour, %(name)s",
        "ru": "Привет, %(name)s", "nl": "Hallo, %(name)s",
        "ja": "こんにちは、%(name)s さん", "el": "Γεια σου, %(name)s",
        "cs": "Ahoj, %(name)s", "zh_Hans": "你好，%(name)s",
        "pt": "Olá, %(name)s", "ko": "안녕하세요, %(name)s 님",
        "pl": "Cześć, %(name)s",
    },
    # ─── Common actions ────────────────────────────────────────────
    "Add": {
        "de": "Hinzufügen", "es": "Añadir", "ar": "أضف", "tr": "Ekle",
        "it": "Aggiungi", "fr": "Ajouter", "ru": "Добавить", "nl": "Toevoegen",
        "ja": "追加", "el": "Προσθήκη", "cs": "Přidat", "zh_Hans": "添加",
        "pt": "Adicionar", "ko": "추가", "pl": "Dodaj",
    },
    "Delete": {
        "de": "Löschen", "es": "Eliminar", "ar": "حذف", "tr": "Sil",
        "it": "Elimina", "fr": "Supprimer", "ru": "Удалить", "nl": "Verwijderen",
        "ja": "削除", "el": "Διαγραφή", "cs": "Smazat", "zh_Hans": "删除",
        "pt": "Excluir", "ko": "삭제", "pl": "Usuń",
    },
    "Edit": {
        "de": "Bearbeiten", "es": "Editar", "ar": "تعديل", "tr": "Düzenle",
        "it": "Modifica", "fr": "Modifier", "ru": "Изменить", "nl": "Bewerken",
        "ja": "編集", "el": "Επεξεργασία", "cs": "Upravit", "zh_Hans": "编辑",
        "pt": "Editar", "ko": "편집", "pl": "Edytuj",
    },
    "Save changes": {
        "de": "Änderungen speichern", "es": "Guardar cambios",
        "ar": "حفظ التغييرات", "tr": "Değişiklikleri kaydet",
        "it": "Salva modifiche", "fr": "Enregistrer les modifications",
        "ru": "Сохранить изменения", "nl": "Wijzigingen opslaan",
        "ja": "変更を保存", "el": "Αποθήκευση αλλαγών", "cs": "Uložit změny",
        "zh_Hans": "保存更改", "pt": "Salvar alterações", "ko": "변경사항 저장",
        "pl": "Zapisz zmiany",
    },
    "Close": {
        "de": "Schließen", "es": "Cerrar", "ar": "إغلاق", "tr": "Kapat",
        "it": "Chiudi", "fr": "Fermer", "ru": "Закрыть", "nl": "Sluiten",
        "ja": "閉じる", "el": "Κλείσιμο", "cs": "Zavřít", "zh_Hans": "关闭",
        "pt": "Fechar", "ko": "닫기", "pl": "Zamknij",
    },
    "Cancel": {
        "de": "Abbrechen", "es": "Cancelar", "ar": "إلغاء", "tr": "İptal",
        "it": "Annulla", "fr": "Annuler", "ru": "Отмена", "nl": "Annuleren",
        "ja": "キャンセル", "el": "Άκυρο", "cs": "Zrušit", "zh_Hans": "取消",
        "pt": "Cancelar", "ko": "취소", "pl": "Anuluj",
    },
    "Continue": {
        "de": "Weiter", "es": "Continuar", "ar": "متابعة", "tr": "Devam et",
        "it": "Continua", "fr": "Continuer", "ru": "Продолжить", "nl": "Verder",
        "ja": "続行", "el": "Συνέχεια", "cs": "Pokračovat", "zh_Hans": "继续",
        "pt": "Continuar", "ko": "계속", "pl": "Kontynuuj",
    },
    "Back to home": {
        "de": "Zurück zur Startseite", "es": "Volver al inicio",
        "ar": "العودة إلى الرئيسية", "tr": "Ana sayfaya dön",
        "it": "Torna alla home", "fr": "Retour à l'accueil",
        "ru": "Вернуться на главную", "nl": "Terug naar home",
        "ja": "ホームに戻る", "el": "Επιστροφή στην αρχική",
        "cs": "Zpět na domů", "zh_Hans": "返回首页", "pt": "Voltar ao início",
        "ko": "홈으로 돌아가기", "pl": "Powrót do strony głównej",
    },
    "Back to menu": {
        "de": "Zurück zum Menü", "es": "Volver al menú", "ar": "العودة إلى القائمة",
        "tr": "Menüye dön", "it": "Torna al menu", "fr": "Retour au menu",
        "ru": "Вернуться в меню", "nl": "Terug naar menu",
        "ja": "メニューへ戻る", "el": "Επιστροφή στο μενού",
        "cs": "Zpět na menu", "zh_Hans": "返回菜单", "pt": "Voltar ao menu",
        "ko": "메뉴로 돌아가기", "pl": "Powrót do menu",
    },
    "Back": {
        "de": "Zurück", "es": "Atrás", "ar": "رجوع", "tr": "Geri",
        "it": "Indietro", "fr": "Retour", "ru": "Назад", "nl": "Terug",
        "ja": "戻る", "el": "Πίσω", "cs": "Zpět", "zh_Hans": "返回",
        "pt": "Voltar", "ko": "뒤로", "pl": "Wróć",
    },
    "Done": {
        "de": "Fertig", "es": "Listo", "ar": "تم", "tr": "Tamam",
        "it": "Fatto", "fr": "Terminé", "ru": "Готово", "nl": "Klaar",
        "ja": "完了", "el": "Έτοιμο", "cs": "Hotovo", "zh_Hans": "完成",
        "pt": "Concluído", "ko": "완료", "pl": "Gotowe",
    },
    "Remove": {
        "de": "Entfernen", "es": "Quitar", "ar": "إزالة", "tr": "Kaldır",
        "it": "Rimuovi", "fr": "Retirer", "ru": "Удалить", "nl": "Verwijderen",
        "ja": "削除", "el": "Αφαίρεση", "cs": "Odebrat", "zh_Hans": "移除",
        "pt": "Remover", "ko": "제거", "pl": "Usuń",
    },
    "Loading…": {
        "de": "Wird geladen…", "es": "Cargando…", "ar": "جارٍ التحميل…",
        "tr": "Yükleniyor…", "it": "Caricamento…", "fr": "Chargement…",
        "ru": "Загрузка…", "nl": "Laden…", "ja": "読み込み中…",
        "el": "Φόρτωση…", "cs": "Načítání…", "zh_Hans": "加载中…",
        "pt": "Carregando…", "ko": "불러오는 중…", "pl": "Ładowanie…",
    },
    "Sending…": {
        "de": "Wird gesendet…", "es": "Enviando…", "ar": "جارٍ الإرسال…",
        "tr": "Gönderiliyor…", "it": "Invio…", "fr": "Envoi…",
        "ru": "Отправка…", "nl": "Verzenden…", "ja": "送信中…",
        "el": "Αποστολή…", "cs": "Odesílání…", "zh_Hans": "发送中…",
        "pt": "Enviando…", "ko": "전송 중…", "pl": "Wysyłanie…",
    },
    # ─── Forms ─────────────────────────────────────────────────────
    "Email": {
        "de": "E-Mail", "es": "Correo electrónico", "ar": "البريد الإلكتروني",
        "tr": "E-posta", "it": "Email", "fr": "E-mail", "ru": "Эл. почта",
        "nl": "E-mail", "ja": "メール", "el": "Email", "cs": "E-mail",
        "zh_Hans": "邮箱", "pt": "E-mail", "ko": "이메일", "pl": "E-mail",
    },
    "Password": {
        "de": "Passwort", "es": "Contraseña", "ar": "كلمة المرور",
        "tr": "Şifre", "it": "Password", "fr": "Mot de passe", "ru": "Пароль",
        "nl": "Wachtwoord", "ja": "パスワード", "el": "Κωδικός",
        "cs": "Heslo", "zh_Hans": "密码", "pt": "Senha", "ko": "비밀번호",
        "pl": "Hasło",
    },
    "Phone": {
        "de": "Telefon", "es": "Teléfono", "ar": "الهاتف", "tr": "Telefon",
        "it": "Telefono", "fr": "Téléphone", "ru": "Телефон",
        "nl": "Telefoon", "ja": "電話", "el": "Τηλέφωνο", "cs": "Telefon",
        "zh_Hans": "电话", "pt": "Telefone", "ko": "전화", "pl": "Telefon",
    },
    "Name": {
        "de": "Name", "es": "Nombre", "ar": "الاسم", "tr": "Ad",
        "it": "Nome", "fr": "Nom", "ru": "Имя", "nl": "Naam",
        "ja": "名前", "el": "Όνομα", "cs": "Jméno", "zh_Hans": "姓名",
        "pt": "Nome", "ko": "이름", "pl": "Imię",
    },
    "Address": {
        "de": "Adresse", "es": "Dirección", "ar": "العنوان", "tr": "Adres",
        "it": "Indirizzo", "fr": "Adresse", "ru": "Адрес", "nl": "Adres",
        "ja": "住所", "el": "Διεύθυνση", "cs": "Adresa", "zh_Hans": "地址",
        "pt": "Endereço", "ko": "주소", "pl": "Adres",
    },
    "City": {
        "de": "Stadt", "es": "Ciudad", "ar": "المدينة", "tr": "Şehir",
        "it": "Città", "fr": "Ville", "ru": "Город", "nl": "Stad",
        "ja": "市", "el": "Πόλη", "cs": "Město", "zh_Hans": "城市",
        "pt": "Cidade", "ko": "도시", "pl": "Miasto",
    },
    "Country": {
        "de": "Land", "es": "País", "ar": "الدولة", "tr": "Ülke",
        "it": "Paese", "fr": "Pays", "ru": "Страна", "nl": "Land",
        "ja": "国", "el": "Χώρα", "cs": "Země", "zh_Hans": "国家",
        "pt": "País", "ko": "국가", "pl": "Kraj",
    },
    "Postal code": {
        "de": "Postleitzahl", "es": "Código postal", "ar": "الرمز البريدي",
        "tr": "Posta kodu", "it": "CAP", "fr": "Code postal",
        "ru": "Почтовый индекс", "nl": "Postcode", "ja": "郵便番号",
        "el": "Ταχ. κώδικας", "cs": "PSČ", "zh_Hans": "邮编",
        "pt": "CEP", "ko": "우편번호", "pl": "Kod pocztowy",
    },
    "Subject": {
        "de": "Betreff", "es": "Asunto", "ar": "الموضوع", "tr": "Konu",
        "it": "Oggetto", "fr": "Sujet", "ru": "Тема", "nl": "Onderwerp",
        "ja": "件名", "el": "Θέμα", "cs": "Předmět", "zh_Hans": "主题",
        "pt": "Assunto", "ko": "제목", "pl": "Temat",
    },
    "Message": {
        "de": "Nachricht", "es": "Mensaje", "ar": "الرسالة", "tr": "Mesaj",
        "it": "Messaggio", "fr": "Message", "ru": "Сообщение",
        "nl": "Bericht", "ja": "メッセージ", "el": "Μήνυμα", "cs": "Zpráva",
        "zh_Hans": "留言", "pt": "Mensagem", "ko": "메시지", "pl": "Wiadomość",
    },
    "Send message": {
        "de": "Nachricht senden", "es": "Enviar mensaje", "ar": "إرسال الرسالة",
        "tr": "Mesaj gönder", "it": "Invia messaggio", "fr": "Envoyer le message",
        "ru": "Отправить сообщение", "nl": "Bericht verzenden",
        "ja": "メッセージ送信", "el": "Αποστολή μηνύματος",
        "cs": "Odeslat zprávu", "zh_Hans": "发送消息", "pt": "Enviar mensagem",
        "ko": "메시지 보내기", "pl": "Wyślij wiadomość",
    },
    "Notes": {
        "de": "Notizen", "es": "Notas", "ar": "ملاحظات", "tr": "Notlar",
        "it": "Note", "fr": "Notes", "ru": "Заметки", "nl": "Notities",
        "ja": "メモ", "el": "Σημειώσεις", "cs": "Poznámky", "zh_Hans": "备注",
        "pt": "Notas", "ko": "메모", "pl": "Notatki",
    },
    "Date": {
        "de": "Datum", "es": "Fecha", "ar": "التاريخ", "tr": "Tarih",
        "it": "Data", "fr": "Date", "ru": "Дата", "nl": "Datum",
        "ja": "日付", "el": "Ημερομηνία", "cs": "Datum", "zh_Hans": "日期",
        "pt": "Data", "ko": "날짜", "pl": "Data",
    },
    "Time": {
        "de": "Uhrzeit", "es": "Hora", "ar": "الوقت", "tr": "Saat",
        "it": "Ora", "fr": "Heure", "ru": "Время", "nl": "Tijd",
        "ja": "時間", "el": "Ώρα", "cs": "Čas", "zh_Hans": "时间",
        "pt": "Hora", "ko": "시간", "pl": "Czas",
    },
    # ─── Menu / cart / orders ──────────────────────────────────────
    "Cart": {
        "de": "Warenkorb", "es": "Carrito", "ar": "السلة", "tr": "Sepet",
        "it": "Carrello", "fr": "Panier", "ru": "Корзина", "nl": "Winkelwagen",
        "ja": "カート", "el": "Καλάθι", "cs": "Košík", "zh_Hans": "购物车",
        "pt": "Carrinho", "ko": "장바구니", "pl": "Koszyk",
    },
    "Your Cart": {
        "de": "Ihr Warenkorb", "es": "Tu carrito", "ar": "سلتك",
        "tr": "Sepetiniz", "it": "Il tuo carrello", "fr": "Votre panier",
        "ru": "Ваша корзина", "nl": "Uw winkelwagen", "ja": "あなたのカート",
        "el": "Το καλάθι σας", "cs": "Váš košík", "zh_Hans": "您的购物车",
        "pt": "Seu carrinho", "ko": "장바구니", "pl": "Twój koszyk",
    },
    "Cart is empty.": {
        "de": "Warenkorb ist leer.", "es": "El carrito está vacío.",
        "ar": "السلة فارغة.", "tr": "Sepet boş.", "it": "Il carrello è vuoto.",
        "fr": "Le panier est vide.", "ru": "Корзина пуста.",
        "nl": "Winkelwagen is leeg.", "ja": "カートは空です。",
        "el": "Το καλάθι είναι άδειο.", "cs": "Košík je prázdný.",
        "zh_Hans": "购物车为空。", "pt": "O carrinho está vazio.",
        "ko": "장바구니가 비어 있습니다.", "pl": "Koszyk jest pusty.",
    },
    "Your cart is empty.": {
        "de": "Ihr Warenkorb ist leer.", "es": "Tu carrito está vacío.",
        "ar": "سلتك فارغة.", "tr": "Sepetiniz boş.",
        "it": "Il tuo carrello è vuoto.", "fr": "Votre panier est vide.",
        "ru": "Ваша корзина пуста.", "nl": "Uw winkelwagen is leeg.",
        "ja": "カートは空です。", "el": "Το καλάθι σας είναι άδειο.",
        "cs": "Váš košík je prázdný.", "zh_Hans": "您的购物车为空。",
        "pt": "Seu carrinho está vazio.", "ko": "장바구니가 비어 있습니다.",
        "pl": "Twój koszyk jest pusty.",
    },
    "Total": {
        "de": "Gesamt", "es": "Total", "ar": "الإجمالي", "tr": "Toplam",
        "it": "Totale", "fr": "Total", "ru": "Итого", "nl": "Totaal",
        "ja": "合計", "el": "Σύνολο", "cs": "Celkem", "zh_Hans": "合计",
        "pt": "Total", "ko": "합계", "pl": "Suma",
    },
    "total": {
        "de": "insgesamt", "es": "total", "ar": "المجموع", "tr": "toplam",
        "it": "totale", "fr": "total", "ru": "всего", "nl": "totaal",
        "ja": "合計", "el": "σύνολο", "cs": "celkem", "zh_Hans": "合计",
        "pt": "total", "ko": "합계", "pl": "razem",
    },
    "Subtotal": {
        "de": "Zwischensumme", "es": "Subtotal", "ar": "المجموع الفرعي",
        "tr": "Ara toplam", "it": "Subtotale", "fr": "Sous-total",
        "ru": "Промежуточный итог", "nl": "Subtotaal", "ja": "小計",
        "el": "Μερικό σύνολο", "cs": "Mezisoučet", "zh_Hans": "小计",
        "pt": "Subtotal", "ko": "소계", "pl": "Suma częściowa",
    },
    "Orders": {
        "de": "Bestellungen", "es": "Pedidos", "ar": "الطلبات",
        "tr": "Siparişler", "it": "Ordini", "fr": "Commandes",
        "ru": "Заказы", "nl": "Bestellingen", "ja": "注文", "el": "Παραγγελίες",
        "cs": "Objednávky", "zh_Hans": "订单", "pt": "Pedidos",
        "ko": "주문", "pl": "Zamówienia",
    },
    "Order": {
        "de": "Bestellung", "es": "Pedido", "ar": "طلب", "tr": "Sipariş",
        "it": "Ordine", "fr": "Commande", "ru": "Заказ", "nl": "Bestelling",
        "ja": "注文", "el": "Παραγγελία", "cs": "Objednávka",
        "zh_Hans": "订单", "pt": "Pedido", "ko": "주문", "pl": "Zamówienie",
    },
    "Order Summary": {
        "de": "Bestellübersicht", "es": "Resumen del pedido",
        "ar": "ملخص الطلب", "tr": "Sipariş özeti", "it": "Riepilogo ordine",
        "fr": "Récapitulatif de commande", "ru": "Итоги заказа",
        "nl": "Besteloverzicht", "ja": "注文概要", "el": "Σύνοψη παραγγελίας",
        "cs": "Souhrn objednávky", "zh_Hans": "订单摘要",
        "pt": "Resumo do pedido", "ko": "주문 요약", "pl": "Podsumowanie",
    },
    "Place Order": {
        "de": "Bestellung aufgeben", "es": "Realizar pedido", "ar": "تنفيذ الطلب",
        "tr": "Sipariş ver", "it": "Ordina", "fr": "Passer la commande",
        "ru": "Оформить заказ", "nl": "Bestelling plaatsen", "ja": "注文する",
        "el": "Υποβολή παραγγελίας", "cs": "Odeslat objednávku",
        "zh_Hans": "下单", "pt": "Fazer pedido", "ko": "주문하기",
        "pl": "Złóż zamówienie",
    },
    "Cash": {
        "de": "Bar", "es": "Efectivo", "ar": "نقدًا", "tr": "Nakit",
        "it": "Contanti", "fr": "Espèces", "ru": "Наличные", "nl": "Contant",
        "ja": "現金", "el": "Μετρητά", "cs": "Hotově", "zh_Hans": "现金",
        "pt": "Dinheiro", "ko": "현금", "pl": "Gotówka",
    },
    "Online": {
        "de": "Online", "es": "En línea", "ar": "عبر الإنترنت", "tr": "Online",
        "it": "Online", "fr": "En ligne", "ru": "Онлайн", "nl": "Online",
        "ja": "オンライン", "el": "Διαδικτυακά", "cs": "Online",
        "zh_Hans": "在线", "pt": "Online", "ko": "온라인", "pl": "Online",
    },
    "Payment": {
        "de": "Zahlung", "es": "Pago", "ar": "الدفع", "tr": "Ödeme",
        "it": "Pagamento", "fr": "Paiement", "ru": "Оплата", "nl": "Betaling",
        "ja": "支払い", "el": "Πληρωμή", "cs": "Platba", "zh_Hans": "支付",
        "pt": "Pagamento", "ko": "결제", "pl": "Płatność",
    },
    "Payment Method": {
        "de": "Zahlungsmethode", "es": "Método de pago", "ar": "طريقة الدفع",
        "tr": "Ödeme yöntemi", "it": "Metodo di pagamento",
        "fr": "Mode de paiement", "ru": "Способ оплаты", "nl": "Betaalmethode",
        "ja": "支払い方法", "el": "Τρόπος πληρωμής", "cs": "Způsob platby",
        "zh_Hans": "支付方式", "pt": "Método de pagamento", "ko": "결제 방법",
        "pl": "Metoda płatności",
    },
    "Dine In": {
        "de": "Vor Ort", "es": "En el local", "ar": "تناول في المكان",
        "tr": "Restoranda", "it": "In loco", "fr": "Sur place",
        "ru": "В зале", "nl": "Ter plaatse", "ja": "店内飲食",
        "el": "Στο κατάστημα", "cs": "V restauraci", "zh_Hans": "堂食",
        "pt": "No local", "ko": "매장 이용", "pl": "Na miejscu",
    },
    "Pickup": {
        "de": "Abholung", "es": "Recogida", "ar": "الاستلام", "tr": "Gel-al",
        "it": "Ritiro", "fr": "À emporter", "ru": "Самовывоз",
        "nl": "Afhalen", "ja": "テイクアウト", "el": "Παραλαβή",
        "cs": "Vyzvednutí", "zh_Hans": "自取", "pt": "Retirar",
        "ko": "포장", "pl": "Odbiór",
    },
    "Delivery": {
        "de": "Lieferung", "es": "Entrega", "ar": "التوصيل", "tr": "Teslimat",
        "it": "Consegna", "fr": "Livraison", "ru": "Доставка",
        "nl": "Bezorging", "ja": "配達", "el": "Παράδοση", "cs": "Doručení",
        "zh_Hans": "配送", "pt": "Entrega", "ko": "배달", "pl": "Dostawa",
    },
    "Reservation": {
        "de": "Reservierung", "es": "Reserva", "ar": "الحجز", "tr": "Rezervasyon",
        "it": "Prenotazione", "fr": "Réservation", "ru": "Бронирование",
        "nl": "Reservering", "ja": "予約", "el": "Κράτηση", "cs": "Rezervace",
        "zh_Hans": "预订", "pt": "Reserva", "ko": "예약", "pl": "Rezerwacja",
    },
    "Table reservation": {
        "de": "Tischreservierung", "es": "Reserva de mesa", "ar": "حجز طاولة",
        "tr": "Masa rezervasyonu", "it": "Prenotazione tavolo",
        "fr": "Réservation de table", "ru": "Бронирование столика",
        "nl": "Tafelreservering", "ja": "テーブル予約",
        "el": "Κράτηση τραπεζιού", "cs": "Rezervace stolu",
        "zh_Hans": "预订餐桌", "pt": "Reserva de mesa", "ko": "테이블 예약",
        "pl": "Rezerwacja stolika",
    },
    "Table Number": {
        "de": "Tischnummer", "es": "Número de mesa", "ar": "رقم الطاولة",
        "tr": "Masa numarası", "it": "Numero tavolo", "fr": "Numéro de table",
        "ru": "Номер столика", "nl": "Tafelnummer", "ja": "テーブル番号",
        "el": "Αριθμός τραπεζιού", "cs": "Číslo stolu", "zh_Hans": "餐桌号",
        "pt": "Número da mesa", "ko": "테이블 번호", "pl": "Numer stolika",
    },
    "Service Type": {
        "de": "Servicetyp", "es": "Tipo de servicio", "ar": "نوع الخدمة",
        "tr": "Servis türü", "it": "Tipo di servizio", "fr": "Type de service",
        "ru": "Тип обслуживания", "nl": "Servicetype", "ja": "サービスタイプ",
        "el": "Τύπος υπηρεσίας", "cs": "Typ služby", "zh_Hans": "服务类型",
        "pt": "Tipo de serviço", "ko": "서비스 유형", "pl": "Rodzaj usługi",
    },
    "Confirm Order": {
        "de": "Bestellung bestätigen", "es": "Confirmar pedido",
        "ar": "تأكيد الطلب", "tr": "Siparişi onayla", "it": "Conferma ordine",
        "fr": "Confirmer la commande", "ru": "Подтвердить заказ",
        "nl": "Bestelling bevestigen", "ja": "注文確認",
        "el": "Επιβεβαίωση παραγγελίας", "cs": "Potvrdit objednávku",
        "zh_Hans": "确认订单", "pt": "Confirmar pedido", "ko": "주문 확인",
        "pl": "Potwierdź zamówienie",
    },
    "Number of guests": {
        "de": "Anzahl der Gäste", "es": "Número de invitados", "ar": "عدد الضيوف",
        "tr": "Misafir sayısı", "it": "Numero di ospiti",
        "fr": "Nombre d'invités", "ru": "Количество гостей",
        "nl": "Aantal gasten", "ja": "ゲストの人数", "el": "Αριθμός καλεσμένων",
        "cs": "Počet hostů", "zh_Hans": "客人数量", "pt": "Número de convidados",
        "ko": "인원 수", "pl": "Liczba gości",
    },
    "Opening Hours": {
        "de": "Öffnungszeiten", "es": "Horario de apertura",
        "ar": "ساعات العمل", "tr": "Açılış saatleri", "it": "Orari di apertura",
        "fr": "Horaires d'ouverture", "ru": "Часы работы",
        "nl": "Openingstijden", "ja": "営業時間", "el": "Ώρες λειτουργίας",
        "cs": "Otevírací doba", "zh_Hans": "营业时间",
        "pt": "Horário de funcionamento", "ko": "영업 시간",
        "pl": "Godziny otwarcia",
    },
    "Opening hours:": {
        "de": "Öffnungszeiten:", "es": "Horario de apertura:",
        "ar": "ساعات العمل:", "tr": "Açılış saatleri:",
        "it": "Orari di apertura:", "fr": "Horaires d'ouverture:",
        "ru": "Часы работы:", "nl": "Openingstijden:", "ja": "営業時間:",
        "el": "Ώρες λειτουργίας:", "cs": "Otevírací doba:",
        "zh_Hans": "营业时间：", "pt": "Horário de funcionamento:",
        "ko": "영업 시간:", "pl": "Godziny otwarcia:",
    },
    # ─── Product / footer ──────────────────────────────────────────
    "Product": {
        "de": "Produkt", "es": "Producto", "ar": "المنتج", "tr": "Ürün",
        "it": "Prodotto", "fr": "Produit", "ru": "Продукт", "nl": "Product",
        "ja": "製品", "el": "Προϊόν", "cs": "Produkt", "zh_Hans": "产品",
        "pt": "Produto", "ko": "제품", "pl": "Produkt",
    },
    "Company": {
        "de": "Unternehmen", "es": "Empresa", "ar": "الشركة", "tr": "Şirket",
        "it": "Azienda", "fr": "Entreprise", "ru": "Компания", "nl": "Bedrijf",
        "ja": "会社", "el": "Εταιρεία", "cs": "Společnost", "zh_Hans": "公司",
        "pt": "Empresa", "ko": "회사", "pl": "Firma",
    },
    "About": {
        "de": "Über uns", "es": "Acerca de", "ar": "من نحن", "tr": "Hakkında",
        "it": "Chi siamo", "fr": "À propos", "ru": "О нас", "nl": "Over ons",
        "ja": "会社概要", "el": "Σχετικά", "cs": "O nás", "zh_Hans": "关于",
        "pt": "Sobre", "ko": "소개", "pl": "O nas",
    },
    "See pricing": {
        "de": "Preise ansehen", "es": "Ver precios", "ar": "اطلع على الأسعار",
        "tr": "Fiyatlara bak", "it": "Vedi prezzi", "fr": "Voir les tarifs",
        "ru": "Смотреть цены", "nl": "Bekijk prijzen", "ja": "料金を見る",
        "el": "Δείτε τιμές", "cs": "Zobrazit ceník", "zh_Hans": "查看价格",
        "pt": "Ver preços", "ko": "요금 보기", "pl": "Zobacz cennik",
    },
    "Get started": {
        "de": "Loslegen", "es": "Empezar", "ar": "ابدأ", "tr": "Başla",
        "it": "Inizia", "fr": "Commencer", "ru": "Начать", "nl": "Aan de slag",
        "ja": "始める", "el": "Ξεκινήστε", "cs": "Začít", "zh_Hans": "开始",
        "pt": "Começar", "ko": "시작하기", "pl": "Zaczynamy",
    },
    "Contact us": {
        "de": "Kontaktieren Sie uns", "es": "Contáctanos", "ar": "اتصل بنا",
        "tr": "Bize ulaşın", "it": "Contattaci", "fr": "Nous contacter",
        "ru": "Свяжитесь с нами", "nl": "Neem contact op", "ja": "お問い合わせ",
        "el": "Επικοινωνήστε", "cs": "Kontaktujte nás", "zh_Hans": "联系我们",
        "pt": "Fale conosco", "ko": "문의하기", "pl": "Skontaktuj się",
    },
    "Get in touch": {
        "de": "Kontakt aufnehmen", "es": "Ponte en contacto", "ar": "تواصل معنا",
        "tr": "İletişime geç", "it": "Mettiti in contatto",
        "fr": "Prenez contact", "ru": "Свяжитесь с нами",
        "nl": "Neem contact op", "ja": "お問い合わせ", "el": "Επικοινωνία",
        "cs": "Kontaktujte nás", "zh_Hans": "取得联系", "pt": "Entre em contato",
        "ko": "연락하기", "pl": "Skontaktuj się",
    },
    # ─── Payment / status ──────────────────────────────────────────
    "Payment successful": {
        "de": "Zahlung erfolgreich", "es": "Pago exitoso",
        "ar": "تم الدفع بنجاح", "tr": "Ödeme başarılı", "it": "Pagamento riuscito",
        "fr": "Paiement réussi", "ru": "Платёж успешен",
        "nl": "Betaling geslaagd", "ja": "支払い完了",
        "el": "Επιτυχής πληρωμή", "cs": "Platba proběhla úspěšně",
        "zh_Hans": "支付成功", "pt": "Pagamento bem-sucedido",
        "ko": "결제 완료", "pl": "Płatność zakończona",
    },
    "Payment cancelled": {
        "de": "Zahlung abgebrochen", "es": "Pago cancelado",
        "ar": "تم إلغاء الدفع", "tr": "Ödeme iptal edildi",
        "it": "Pagamento annullato", "fr": "Paiement annulé",
        "ru": "Платёж отменён", "nl": "Betaling geannuleerd",
        "ja": "支払いキャンセル", "el": "Ακύρωση πληρωμής",
        "cs": "Platba zrušena", "zh_Hans": "支付已取消",
        "pt": "Pagamento cancelado", "ko": "결제 취소됨",
        "pl": "Płatność anulowana",
    },
    "Page Not Found": {
        "de": "Seite nicht gefunden", "es": "Página no encontrada",
        "ar": "الصفحة غير موجودة", "tr": "Sayfa bulunamadı",
        "it": "Pagina non trovata", "fr": "Page introuvable",
        "ru": "Страница не найдена", "nl": "Pagina niet gevonden",
        "ja": "ページが見つかりません", "el": "Η σελίδα δεν βρέθηκε",
        "cs": "Stránka nenalezena", "zh_Hans": "页面未找到",
        "pt": "Página não encontrada", "ko": "페이지를 찾을 수 없습니다",
        "pl": "Nie znaleziono strony",
    },
    "Page not found": {
        "de": "Seite nicht gefunden", "es": "Página no encontrada",
        "ar": "الصفحة غير موجودة", "tr": "Sayfa bulunamadı",
        "it": "Pagina non trovata", "fr": "Page introuvable",
        "ru": "Страница не найдена", "nl": "Pagina niet gevonden",
        "ja": "ページが見つかりません", "el": "Η σελίδα δεν βρέθηκε",
        "cs": "Stránka nenalezena", "zh_Hans": "页面未找到",
        "pt": "Página não encontrada", "ko": "페이지를 찾을 수 없습니다",
        "pl": "Nie znaleziono strony",
    },
    "Server Error": {
        "de": "Serverfehler", "es": "Error del servidor",
        "ar": "خطأ في الخادم", "tr": "Sunucu hatası",
        "it": "Errore del server", "fr": "Erreur serveur",
        "ru": "Ошибка сервера", "nl": "Serverfout", "ja": "サーバーエラー",
        "el": "Σφάλμα διακομιστή", "cs": "Chyba serveru",
        "zh_Hans": "服务器错误", "pt": "Erro no servidor",
        "ko": "서버 오류", "pl": "Błąd serwera",
    },
    "Something went wrong": {
        "de": "Etwas ist schiefgelaufen", "es": "Algo salió mal",
        "ar": "حدث خطأ ما", "tr": "Bir şeyler yanlış gitti",
        "it": "Qualcosa è andato storto", "fr": "Une erreur s'est produite",
        "ru": "Что-то пошло не так", "nl": "Er is iets misgegaan",
        "ja": "問題が発生しました", "el": "Κάτι πήγε στραβά",
        "cs": "Něco se pokazilo", "zh_Hans": "出错了",
        "pt": "Algo deu errado", "ko": "문제가 발생했습니다",
        "pl": "Coś poszło nie tak",
    },
    "Simple QR Code,": {
        "de": "Einfacher QR-Code,", "es": "Código QR sencillo,",
        "ar": "رمز QR بسيط،", "tr": "Basit QR Kod,",
        "it": "QR code semplice,", "fr": "Code QR simple,",
        "ru": "Простой QR-код,", "nl": "Eenvoudige QR-code,",
        "ja": "シンプルなQRコード、", "el": "Απλός κωδικός QR,",
        "cs": "Jednoduchý QR kód,", "zh_Hans": "简单的二维码，",
        "pt": "Código QR simples,", "ko": "간단한 QR 코드,",
        "pl": "Prosty kod QR,",
    },
    "More Revenue.": {
        "de": "Mehr Umsatz.", "es": "Más ingresos.", "ar": "دخل أكثر.",
        "tr": "Daha fazla gelir.", "it": "Più ricavi.", "fr": "Plus de revenus.",
        "ru": "Больше дохода.", "nl": "Meer omzet.", "ja": "収益アップ。",
        "el": "Περισσότερα έσοδα.", "cs": "Vyšší tržby.", "zh_Hans": "更多收入。",
        "pt": "Mais receita.", "ko": "더 많은 수익.", "pl": "Większy przychód.",
    },
    "View Example": {
        "de": "Beispiel ansehen", "es": "Ver ejemplo", "ar": "شاهد مثالاً",
        "tr": "Örnek gör", "it": "Vedi esempio", "fr": "Voir l'exemple",
        "ru": "Смотреть пример", "nl": "Voorbeeld bekijken", "ja": "例を見る",
        "el": "Δείτε παράδειγμα", "cs": "Zobrazit příklad",
        "zh_Hans": "查看示例", "pt": "Ver exemplo", "ko": "예시 보기",
        "pl": "Zobacz przykład",
    },
    "See Menus": {
        "de": "Menüs ansehen", "es": "Ver menús", "ar": "شاهد القوائم",
        "tr": "Menülere göz at", "it": "Vedi menu", "fr": "Voir les menus",
        "ru": "Смотреть меню", "nl": "Bekijk menu's", "ja": "メニューを見る",
        "el": "Δείτε μενού", "cs": "Prohlédnout menu", "zh_Hans": "查看菜单",
        "pt": "Ver menus", "ko": "메뉴 보기", "pl": "Zobacz menu",
    },
    "View menu": {
        "de": "Menü ansehen", "es": "Ver menú", "ar": "عرض القائمة",
        "tr": "Menüyü gör", "it": "Vedi menu", "fr": "Voir le menu",
        "ru": "Смотреть меню", "nl": "Menu bekijken", "ja": "メニューを見る",
        "el": "Δείτε μενού", "cs": "Zobrazit menu", "zh_Hans": "查看菜单",
        "pt": "Ver menu", "ko": "메뉴 보기", "pl": "Zobacz menu",
    },
    "Add to cart": {
        "de": "In den Warenkorb", "es": "Añadir al carrito",
        "ar": "أضف إلى السلة", "tr": "Sepete ekle", "it": "Aggiungi al carrello",
        "fr": "Ajouter au panier", "ru": "В корзину", "nl": "Aan winkelwagen",
        "ja": "カートに追加", "el": "Προσθήκη στο καλάθι",
        "cs": "Přidat do košíku", "zh_Hans": "加入购物车",
        "pt": "Adicionar ao carrinho", "ko": "장바구니에 담기",
        "pl": "Dodaj do koszyka",
    },
    "Added to cart": {
        "de": "Zum Warenkorb hinzugefügt", "es": "Añadido al carrito",
        "ar": "أضيف إلى السلة", "tr": "Sepete eklendi",
        "it": "Aggiunto al carrello", "fr": "Ajouté au panier",
        "ru": "Добавлено в корзину", "nl": "Toegevoegd aan winkelwagen",
        "ja": "カートに追加しました", "el": "Προστέθηκε στο καλάθι",
        "cs": "Přidáno do košíku", "zh_Hans": "已加入购物车",
        "pt": "Adicionado ao carrinho", "ko": "장바구니에 담김",
        "pl": "Dodano do koszyka",
    },
    "Search menu items...": {
        "de": "Menü-Artikel suchen...", "es": "Buscar artículos...",
        "ar": "ابحث في القائمة...", "tr": "Menüde ara...",
        "it": "Cerca articoli...", "fr": "Rechercher dans le menu...",
        "ru": "Поиск по меню...", "nl": "Menu-items zoeken...",
        "ja": "メニューを検索...", "el": "Αναζήτηση μενού...",
        "cs": "Hledat v menu...", "zh_Hans": "搜索菜单...",
        "pt": "Buscar itens...", "ko": "메뉴 검색...", "pl": "Szukaj w menu...",
    },
    "All Categories": {
        "de": "Alle Kategorien", "es": "Todas las categorías",
        "ar": "كل الفئات", "tr": "Tüm kategoriler", "it": "Tutte le categorie",
        "fr": "Toutes les catégories", "ru": "Все категории",
        "nl": "Alle categorieën", "ja": "全カテゴリ", "el": "Όλες οι κατηγορίες",
        "cs": "Všechny kategorie", "zh_Hans": "所有分类",
        "pt": "Todas as categorias", "ko": "모든 카테고리",
        "pl": "Wszystkie kategorie",
    },
    "All categories": {
        "de": "Alle Kategorien", "es": "Todas las categorías",
        "ar": "كل الفئات", "tr": "Tüm kategoriler", "it": "Tutte le categorie",
        "fr": "Toutes les catégories", "ru": "Все категории",
        "nl": "Alle categorieën", "ja": "全カテゴリ", "el": "Όλες οι κατηγορίες",
        "cs": "Všechny kategorie", "zh_Hans": "所有分类",
        "pt": "Todas as categorias", "ko": "모든 카테고리",
        "pl": "Wszystkie kategorie",
    },
    "All": {
        "de": "Alle", "es": "Todo", "ar": "الكل", "tr": "Tümü",
        "it": "Tutti", "fr": "Tous", "ru": "Все", "nl": "Alles",
        "ja": "全て", "el": "Όλα", "cs": "Vše", "zh_Hans": "全部",
        "pt": "Tudo", "ko": "전체", "pl": "Wszystko",
    },
    "Learn More": {
        "de": "Mehr erfahren", "es": "Saber más", "ar": "اعرف المزيد",
        "tr": "Daha fazla bilgi", "it": "Scopri di più",
        "fr": "En savoir plus", "ru": "Узнать больше", "nl": "Meer info",
        "ja": "詳細を見る", "el": "Μάθε περισσότερα", "cs": "Zjistit více",
        "zh_Hans": "了解更多", "pt": "Saiba mais", "ko": "자세히 보기",
        "pl": "Dowiedz się więcej",
    },
    "View orders": {
        "de": "Bestellungen ansehen", "es": "Ver pedidos", "ar": "عرض الطلبات",
        "tr": "Siparişleri gör", "it": "Vedi ordini",
        "fr": "Voir les commandes", "ru": "Просмотр заказов",
        "nl": "Bestellingen bekijken", "ja": "注文を見る",
        "el": "Δείτε παραγγελίες", "cs": "Zobrazit objednávky",
        "zh_Hans": "查看订单", "pt": "Ver pedidos", "ko": "주문 보기",
        "pl": "Zobacz zamówienia",
    },
    # ─── Testimonials (landing) ────────────────────────────────────
    "Owner, Basil House": {
        "de": "Inhaberin, Basil House", "es": "Propietaria, Basil House",
        "ar": "مالكة، بازل هاوس", "tr": "Sahibi, Basil House",
        "it": "Proprietaria, Basil House", "fr": "Propriétaire, Basil House",
        "ru": "Владелица, Basil House", "nl": "Eigenaar, Basil House",
        "ja": "オーナー、Basil House", "el": "Ιδιοκτήτρια, Basil House",
        "cs": "Majitelka, Basil House", "zh_Hans": "老板，Basil House",
        "pt": "Proprietária, Basil House", "ko": "사장, Basil House",
        "pl": "Właścicielka, Basil House",
    },
    "We increased table turnover with faster ordering.": {
        "de": "Wir haben den Tischumsatz mit schnelleren Bestellungen erhöht.",
        "es": "Aumentamos la rotación de mesas con pedidos más rápidos.",
        "ar": "زدنا معدل دوران الطاولات مع طلبات أسرع.",
        "tr": "Daha hızlı siparişle masa devir hızını artırdık.",
        "it": "Abbiamo aumentato la rotazione dei tavoli con ordini più rapidi.",
        "fr": "Nous avons augmenté le taux de rotation des tables grâce à des commandes plus rapides.",
        "ru": "Мы увеличили оборачиваемость столов благодаря быстрым заказам.",
        "nl": "We hebben de tafelrotatie verhoogd met snellere bestellingen.",
        "ja": "より速い注文でテーブル回転率を上げました。",
        "el": "Αυξήσαμε την εναλλαγή τραπεζιών με πιο γρήγορες παραγγελίες.",
        "cs": "Zvýšili jsme obrat stolů díky rychlejšímu objednávání.",
        "zh_Hans": "通过更快下单，我们提升了餐桌翻台率。",
        "pt": "Aumentamos o giro das mesas com pedidos mais rápidos.",
        "ko": "더 빠른 주문으로 테이블 회전율을 높였습니다.",
        "pl": "Zwiększyliśmy rotację stolików dzięki szybszym zamówieniom.",
    },
    "Manager, South Fork": {
        "de": "Manager, South Fork", "es": "Gerente, South Fork",
        "ar": "مدير، ساوث فورك", "tr": "Müdür, South Fork",
        "it": "Manager, South Fork", "fr": "Manager, South Fork",
        "ru": "Менеджер, South Fork", "nl": "Manager, South Fork",
        "ja": "マネージャー、South Fork", "el": "Διευθυντής, South Fork",
        "cs": "Manažer, South Fork", "zh_Hans": "经理，South Fork",
        "pt": "Gerente, South Fork", "ko": "매니저, South Fork",
        "pl": "Menedżer, South Fork",
    },
    "Campaigns helped us fill off-peak hours.": {
        "de": "Kampagnen halfen uns, Nebenzeiten zu füllen.",
        "es": "Las campañas nos ayudaron a llenar las horas valle.",
        "ar": "ساعدتنا الحملات على ملء ساعات الذروة المنخفضة.",
        "tr": "Kampanyalar, yoğun olmayan saatleri doldurmamıza yardımcı oldu.",
        "it": "Le campagne ci hanno aiutato a riempire le ore di scarso afflusso.",
        "fr": "Les campagnes nous ont aidés à remplir les heures creuses.",
        "ru": "Кампании помогли нам заполнить непиковые часы.",
        "nl": "Campagnes hielpen ons daluren te vullen.",
        "ja": "キャンペーンでオフピーク時間を埋めることができました。",
        "el": "Οι εκστρατείες μας βοήθησαν να γεμίσουμε τις ώρες χαμηλής κίνησης.",
        "cs": "Kampaně nám pomohly zaplnit hodiny mimo špičku.",
        "zh_Hans": "营销活动帮助我们填满了淡季时段。",
        "pt": "As campanhas nos ajudaram a preencher horários de baixa demanda.",
        "ko": "캠페인 덕분에 한산한 시간대를 채울 수 있었습니다.",
        "pl": "Kampanie pomogły nam zapełnić godziny poza szczytem.",
    },
    "Founder, Luna Cafe": {
        "de": "Gründerin, Luna Cafe", "es": "Fundadora, Luna Cafe",
        "ar": "المؤسسة، لونا كافيه", "tr": "Kurucu, Luna Cafe",
        "it": "Fondatrice, Luna Cafe", "fr": "Fondatrice, Luna Cafe",
        "ru": "Основательница, Luna Cafe", "nl": "Oprichter, Luna Cafe",
        "ja": "創設者、Luna Cafe", "el": "Ιδρύτρια, Luna Cafe",
        "cs": "Zakladatelka, Luna Cafe", "zh_Hans": "创始人，Luna Cafe",
        "pt": "Fundadora, Luna Cafe", "ko": "창립자, Luna Cafe",
        "pl": "Założycielka, Luna Cafe",
    },
    "Our staff now spends less time taking manual orders.": {
        "de": "Unser Personal verbringt jetzt weniger Zeit mit manuellen Bestellungen.",
        "es": "Nuestro personal ahora dedica menos tiempo a tomar pedidos manuales.",
        "ar": "يقضي موظفونا الآن وقتًا أقل في أخذ الطلبات يدويًا.",
        "tr": "Personelimiz artık manuel sipariş almak için daha az zaman harcıyor.",
        "it": "Il nostro personale dedica meno tempo alla presa manuale degli ordini.",
        "fr": "Notre personnel passe désormais moins de temps à prendre les commandes manuellement.",
        "ru": "Наш персонал теперь тратит меньше времени на ручной приём заказов.",
        "nl": "Ons personeel besteedt nu minder tijd aan handmatig bestellingen opnemen.",
        "ja": "スタッフが手動で注文を取る時間が減りました。",
        "el": "Το προσωπικό μας ξοδεύει πλέον λιγότερο χρόνο για χειροκίνητες παραγγελίες.",
        "cs": "Náš personál nyní tráví méně času ručním přijímáním objednávek.",
        "zh_Hans": "员工现在花在手动接单上的时间更少了。",
        "pt": "Nossa equipe agora gasta menos tempo anotando pedidos manualmente.",
        "ko": "직원들이 이제 수동으로 주문 받는 시간이 줄었습니다.",
        "pl": "Nasz zespół spędza teraz mniej czasu na ręcznym przyjmowaniu zamówień.",
    },
    # ─── Feature list keys (landing/features) ──────────────────────
    "AI menu import": {
        "de": "KI-Menü-Import", "es": "Importación de menú con IA",
        "ar": "استيراد القائمة بالذكاء الاصطناعي", "tr": "AI menü içe aktarma",
        "it": "Importazione menu con IA", "fr": "Import de menu par IA",
        "ru": "ИИ-импорт меню", "nl": "AI-menu-import",
        "ja": "AIメニューインポート", "el": "Εισαγωγή μενού με AI",
        "cs": "AI import menu", "zh_Hans": "AI 菜单导入",
        "pt": "Importação de menu com IA", "ko": "AI 메뉴 가져오기",
        "pl": "Import menu z AI",
    },
    "Multilingual menus": {
        "de": "Mehrsprachige Menüs", "es": "Menús multilingües",
        "ar": "قوائم متعددة اللغات", "tr": "Çok dilli menüler",
        "it": "Menu multilingue", "fr": "Menus multilingues",
        "ru": "Многоязычные меню", "nl": "Meertalige menu's",
        "ja": "多言語メニュー", "el": "Πολύγλωσσα μενού",
        "cs": "Vícejazyčná menu", "zh_Hans": "多语言菜单",
        "pt": "Menus multilíngues", "ko": "다국어 메뉴",
        "pl": "Menu wielojęzyczne",
    },
    "QR code generation": {
        "de": "QR-Code-Generierung", "es": "Generación de códigos QR",
        "ar": "إنشاء رموز QR", "tr": "QR kod oluşturma",
        "it": "Generazione codici QR", "fr": "Génération de codes QR",
        "ru": "Генерация QR-кодов", "nl": "QR-code genereren",
        "ja": "QRコード生成", "el": "Δημιουργία κωδικών QR",
        "cs": "Generování QR kódů", "zh_Hans": "生成二维码",
        "pt": "Geração de códigos QR", "ko": "QR 코드 생성",
        "pl": "Generowanie kodów QR",
    },
    "Order management": {
        "de": "Bestellverwaltung", "es": "Gestión de pedidos",
        "ar": "إدارة الطلبات", "tr": "Sipariş yönetimi",
        "it": "Gestione ordini", "fr": "Gestion des commandes",
        "ru": "Управление заказами", "nl": "Bestelbeheer",
        "ja": "注文管理", "el": "Διαχείριση παραγγελιών",
        "cs": "Správa objednávek", "zh_Hans": "订单管理",
        "pt": "Gestão de pedidos", "ko": "주문 관리",
        "pl": "Zarządzanie zamówieniami",
    },
    "Campaign engine": {
        "de": "Kampagnen-Engine", "es": "Motor de campañas",
        "ar": "محرك الحملات", "tr": "Kampanya motoru",
        "it": "Motore di campagne", "fr": "Moteur de campagnes",
        "ru": "Движок кампаний", "nl": "Campagne-engine",
        "ja": "キャンペーンエンジン", "el": "Μηχανή εκστρατειών",
        "cs": "Modul kampaní", "zh_Hans": "营销引擎",
        "pt": "Motor de campanhas", "ko": "캠페인 엔진",
        "pl": "Silnik kampanii",
    },
    "Daily analytics": {
        "de": "Tägliche Analytik", "es": "Analítica diaria",
        "ar": "التحليلات اليومية", "tr": "Günlük analitik",
        "it": "Analisi giornaliere", "fr": "Analyses quotidiennes",
        "ru": "Ежедневная аналитика", "nl": "Dagelijkse analyses",
        "ja": "日次分析", "el": "Καθημερινή αναλυτική",
        "cs": "Denní analytika", "zh_Hans": "每日分析",
        "pt": "Análise diária", "ko": "일일 분석",
        "pl": "Codzienna analityka",
    },
    "Category controls": {
        "de": "Kategoriesteuerung", "es": "Controles de categorías",
        "ar": "التحكم بالفئات", "tr": "Kategori kontrolleri",
        "it": "Controlli categorie", "fr": "Contrôles des catégories",
        "ru": "Управление категориями", "nl": "Categoriebeheer",
        "ja": "カテゴリー管理", "el": "Έλεγχοι κατηγοριών",
        "cs": "Ovládání kategorií", "zh_Hans": "分类控制",
        "pt": "Controles de categorias", "ko": "카테고리 관리",
        "pl": "Kontrola kategorii",
    },
    "Live availability": {
        "de": "Live-Verfügbarkeit", "es": "Disponibilidad en vivo",
        "ar": "التوفر المباشر", "tr": "Canlı stok durumu",
        "it": "Disponibilità in tempo reale", "fr": "Disponibilité en direct",
        "ru": "Доступность в реальном времени", "nl": "Live beschikbaarheid",
        "ja": "リアルタイム在庫", "el": "Ζωντανή διαθεσιμότητα",
        "cs": "Živá dostupnost", "zh_Hans": "实时库存",
        "pt": "Disponibilidade em tempo real", "ko": "실시간 재고",
        "pl": "Dostępność na żywo",
    },
    "POS-ready payloads": {
        "de": "POS-fertige Datenpakete", "es": "Datos listos para POS",
        "ar": "بيانات جاهزة لنظام POS", "tr": "POS uyumlu veri paketleri",
        "it": "Payload pronti per POS", "fr": "Données prêtes pour POS",
        "ru": "Готовые данные для POS", "nl": "POS-klare payloads",
        "ja": "POS対応データ", "el": "Δεδομένα έτοιμα για POS",
        "cs": "Data připravená pro POS", "zh_Hans": "POS 就绪数据",
        "pt": "Dados prontos para POS", "ko": "POS 대응 데이터",
        "pl": "Dane gotowe dla POS",
    },
    "Mobile-first pages": {
        "de": "Mobile-first Seiten", "es": "Páginas mobile-first",
        "ar": "صفحات مصممة للجوال أولاً", "tr": "Mobil öncelikli sayfalar",
        "it": "Pagine mobile-first", "fr": "Pages mobile-first",
        "ru": "Страницы mobile-first", "nl": "Mobile-first pagina's",
        "ja": "モバイルファーストページ", "el": "Σελίδες mobile-first",
        "cs": "Stránky mobile-first", "zh_Hans": "移动优先页面",
        "pt": "Páginas mobile-first", "ko": "모바일 우선 페이지",
        "pl": "Strony mobile-first",
    },
    "Role-ready panel": {
        "de": "Rollenfähiges Panel", "es": "Panel con roles",
        "ar": "لوحة جاهزة للأدوار", "tr": "Rol destekli panel",
        "it": "Pannello con ruoli", "fr": "Panneau avec rôles",
        "ru": "Панель с ролями", "nl": "Rol-klaar paneel",
        "ja": "ロール対応パネル", "el": "Πίνακας με ρόλους",
        "cs": "Panel s rolemi", "zh_Hans": "角色权限面板",
        "pt": "Painel com funções", "ko": "역할 지원 패널",
        "pl": "Panel z rolami",
    },
    "Conversion focused UI": {
        "de": "Conversion-fokussierte Oberfläche",
        "es": "UI enfocada en conversión",
        "ar": "واجهة تركز على التحويل", "tr": "Dönüşüm odaklı arayüz",
        "it": "UI orientata alla conversione",
        "fr": "Interface axée sur la conversion",
        "ru": "Интерфейс, нацеленный на конверсию",
        "nl": "Op conversie gerichte UI", "ja": "コンバージョン重視UI",
        "el": "UI εστιασμένο στη μετατροπή",
        "cs": "UI zaměřené na konverzi", "zh_Hans": "转化优化界面",
        "pt": "Interface focada em conversão", "ko": "전환 최적화 UI",
        "pl": "Interfejs skupiony na konwersji",
    },
}


def _po_escape(s: str) -> str:
    """Escape a string for the msgstr line of a .po file."""
    return (
        s.replace("\\", "\\\\")
         .replace("\"", "\\\"")
         .replace("\n", "\\n")
    )


def process_po(path: Path, lang: str) -> tuple[int, int]:
    """Fill msgstr for known msgids. Returns (filled, total)."""
    text = path.read_text(encoding="utf-8")
    # Split header (before first blank line after leading comments) from body.
    # We rely on the block structure: each entry ends with a blank line.
    lines = text.split("\n")

    out: list[str] = []
    i = 0
    filled = 0
    total = 0
    while i < len(lines):
        # Detect an msgid block: possibly preceded by comments (#) and a msgctxt
        block_start = i
        # skip through leading comments to find msgid
        j = i
        while j < len(lines) and lines[j].startswith("#"):
            j += 1
        if j < len(lines) and lines[j].startswith("msgid "):
            # Parse msgid (may span multiple lines: "" continuations)
            msgid_lines: list[str] = []
            # first line: msgid "..."
            m = re.match(r'^msgid "(.*)"$', lines[j])
            if m:
                msgid_lines.append(m.group(1))
            k = j + 1
            while k < len(lines) and lines[k].startswith("\""):
                m = re.match(r'^"(.*)"$', lines[k])
                if m:
                    msgid_lines.append(m.group(1))
                k += 1
            msgid = "".join(msgid_lines)
            # Unescape common sequences (\n, \")
            msgid_un = msgid.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")

            # Now parse msgstr block (single or multi-line)
            if k < len(lines) and lines[k].startswith("msgstr "):
                # emit up to and including msgid lines
                for x in range(block_start, k):
                    out.append(lines[x])
                # Detect plural form (msgstr[0] etc.) — skip those, keep original
                if lines[k].startswith("msgstr["):
                    # Copy plural block verbatim
                    while k < len(lines) and lines[k] != "":
                        out.append(lines[k])
                        k += 1
                    if k < len(lines):
                        out.append(lines[k])  # blank line
                        k += 1
                    i = k
                    continue

                # Non-plural msgstr
                # Check if we have a translation
                total += 1 if msgid else 0
                translation = T.get(msgid_un, {}).get(lang, "")
                if msgid and translation:
                    # Emit new msgstr with escaped value
                    out.append('msgstr "' + _po_escape(translation) + '"')
                    filled += 1
                    # skip old msgstr line(s)
                    k += 1
                    while k < len(lines) and lines[k].startswith("\""):
                        k += 1
                else:
                    # Keep original msgstr (empty or already-translated) — walk through
                    out.append(lines[k])
                    k += 1
                    while k < len(lines) and lines[k].startswith("\""):
                        out.append(lines[k])
                        k += 1
                # trailing blank line
                if k < len(lines):
                    out.append(lines[k])
                    k += 1
                i = k
                continue
        # Not an entry start — copy verbatim
        out.append(lines[i])
        i += 1

    path.write_text("\n".join(out), encoding="utf-8")
    return filled, total


def main() -> None:
    for lang_dir in sorted(LOCALE_DIR.iterdir()):
        if not lang_dir.is_dir():
            continue
        lang = lang_dir.name
        if lang == "en":
            continue  # source language, no translation needed
        po = lang_dir / "LC_MESSAGES" / "django.po"
        if not po.exists():
            print(f"[skip] {lang}: no django.po")
            continue
        # Django writes zh_Hans on disk; our T uses zh_Hans as key
        filled, total = process_po(po, lang)
        print(f"[{lang}] filled {filled}/{total}")


if __name__ == "__main__":
    main()
