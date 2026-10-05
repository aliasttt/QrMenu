# App registration return

Open `https://preismenu.de/auth/register/?source=app` in a browser that keeps
first-party session cookies. App intent survives retries and language changes;
the pending verification is also stored server-side for page reloads. No password,
verification code, captcha token, or login token is placed in browser storage or URLs.

Only after email verification and successful account creation does the website
return `myqrmenu://register-complete?email=<URL-encoded-email>`. It displays the
success screen and manual return button, then attempts to open that URL once.
There is no timed store redirect. The email is a sign-in hint, never authentication.
Ordinary web signup still signs in and opens the web panel.

Store links have one source in `config/settings.py`, used through the shared
template context. Legacy `APP_ANDROID_URL`, `APP_ANDROID_QR_MENU`, and `APP_IOS_URL`
environment overrides no longer control these links. No admin model stores them.

## Mobile handoff and device acceptance

No iOS/Android application source is present in this web repository; APK files
are not source. The mobile implementation is not verified by the web tests.

- Register the `myqrmenu` URL scheme in both iOS and Android app configuration.
- Handle `register-complete` as the URL host (the path is empty), accepting only
  the agreed scheme/host. Decode the `email` query parameter exactly once, keeping
  literal plus signs (`%2B`) intact. Do not treat email as a session or access grant.
- Handle both initial launch from a closed app and URL delivery to a running or
  backgrounded app. Open the sign-in stage with the email prefilled, per contract.
- On physical iOS and Android devices, test completed signup in both app states,
  blocked automatic launch followed by the manual button, and missing-app install
  links. No callback may occur on an invalid code or failed account creation.
- Web/API tests and HTTP 200 checks do not prove that a device opened the app.
