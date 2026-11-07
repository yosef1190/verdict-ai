# Verdict (Next.js + Firebase Auth + email OTP)

## How sign-in works
- **Google**: popup, no code needed (Google already verified the email).
- **Email + password (sign up and log in)**: the server checks/creates the account, emails a 6-digit code, and only after the code is verified does it hand the browser a Firebase session (custom token with an `otp: true` claim). Codes are single-use, expire in 10 minutes, allow 5 tries, and can be resent every 30 seconds.
- The app signs out any password session that doesn't carry `otp: true`, so signing in directly with the public Firebase API key doesn't count. If you add your own backend, check that claim (or `firebase.sign_in_provider === "google.com"`) on every request.

## Setup
1. Firebase console → Authentication → Sign-in method: enable **Google** and **Email/Password**.
2. Firebase console → **Firestore Database** → create one (production mode; leave rules locked — only the server touches the `otps` collection).
3. Firebase console → Project settings → Service accounts → **Generate new private key**. Put `client_email` and `private_key` in `.env.local` (see `.env.local.example`).
4. Set `OTP_SECRET` (`openssl rand -base64 32`).
5. Email: create a [Resend](https://resend.com) API key → `RESEND_API_KEY`. Verify your sending domain and set `OTP_FROM_EMAIL`. (Resend's test sender only delivers to your own address.) **Dev shortcut:** leave `RESEND_API_KEY` empty and codes print in the terminal.
6. Add your production domain under Authentication → Settings → Authorized domains.

```
npm install
npm run dev
```

## Routes
- `/login`, `/signup` — auth pages (both have "Back to home"; the logo links home everywhere).
- `/api/auth/{signup,login,verify,resend}` — server routes. Add IP-based rate limiting (e.g. Upstash) before going public; the 30s per-email cooldown and 5-try limit are built in.
