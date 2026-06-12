# Installing the iOS app without a Mac or an Apple Developer account

You don't have a Mac and you don't have a paid Apple Developer account ($99/yr). That's fine — you
can still build the app in the cloud and install it on an iPhone from your **Windows 11 PC** using a
**free Apple ID**. The trade-off: a free Apple ID can only sign an app for **7 days**, so you
re-install (one click) once a week. Good enough for you + Ken to test the password-free Church login.

There are two halves: **(1) build the app** (happens automatically in GitHub Actions — no Mac needed)
and **(2) sideload it** (on your Windows PC, with the iPhone plugged in).

---

## 1. Build the app (cloud, no Mac)

GitHub Actions builds the app on a macOS runner every time `native/ios/**` changes, and now also
**packages an unsigned `.ipa`** (the installable file) and uploads it as a downloadable artifact.

1. Go to the repo on GitHub → **Actions** tab → **"Build native iOS (PoC)"**.
2. Open the most recent green run (or click **Run workflow** → branch `main` to start a fresh one).
3. Scroll to the bottom, under **Artifacts**, download **`covenant-path-ios-unsigned-ipa`**.
4. Unzip it — inside is **`CovenantPath.ipa`**. That's the file you'll install.

The build injects the real Supabase URL / anon key / broker URL (from the repo secrets) so the
installed app actually connects — it's a working build, not a config screen.

> The `.ipa` is **unsigned**. That's expected — the sideloading tool signs it with *your* Apple ID
> at install time. Never commit secrets; the anon key in the build is the public, RLS-safe one.

---

## 2. Sideload to your iPhone (Windows 11)

Pick **one** tool. **Sideloadly** is the simplest one-off; **AltStore/SideStore** is nicer if you'll
re-install often (it can refresh over Wi-Fi). Both are free and both run on Windows.

### What you need either way
- Your iPhone + its USB cable.
- A **free Apple ID** (you can make a throwaway one just for this — no payment, no developer program).
  ⚠️ Don't use an Apple ID with important data as your *signing* ID if you're cautious; a dedicated
  free Apple ID is fine and keeps the 3-app sideload limit separate from your real account.
- **Apple Devices app** (or iTunes) from the Microsoft Store — provides the USB drivers Windows needs
  to talk to the iPhone. Install it and open it once so it sees your phone.
- **iCloud for Windows** (Microsoft Store) — AltStore needs it for the same drivers. (Sideloadly
  bundles what it needs but installing these avoids "device not found" headaches.)

### Option A — Sideloadly (quickest for a one-off)
1. Download Sideloadly for Windows from <https://sideloadly.io> and install it.
2. Plug in the iPhone, unlock it, tap **Trust** on the "Trust this computer?" prompt.
3. Open Sideloadly. It should show your device at the top. Drag **`CovenantPath.ipa`** onto the
   Sideloadly window (or click the IPA field and pick it).
4. Enter your **Apple ID** (the signing one) in the Apple account field.
5. Click **Start**. Enter the Apple ID password when asked (if the account has 2FA, generate an
   **app-specific password** at <https://account.apple.com> → Sign-In and Security → App-Specific
   Passwords, and paste that instead).
6. It installs to the phone. First launch will fail with "Untrusted Developer" — that's step 3 below.

### Option B — AltStore / SideStore (best if you'll re-install weekly)
1. Install **AltServer** for Windows from <https://altstore.io>.
2. Plug in the iPhone, unlock, tap **Trust**.
3. In the Windows system tray, click the **AltServer** icon → **Install AltStore** → pick your device
   → sign in with your Apple ID (app-specific password if 2FA).
4. On the iPhone, an **AltStore** app appears. Open it, go to **My Apps** → **+** (top-left) →
   choose the **`CovenantPath.ipa`** you downloaded (AirDrop/email/USB the file to the phone, or use
   AltStore's "Open file"). Enter your Apple ID when prompted.
5. AltStore installs it and can **refresh it over Wi-Fi** before the 7 days expire (keep AltServer
   running on the PC and the phone on the same network). SideStore (<https://sidestore.io>) is a
   fork that refreshes without needing the PC running all the time — worth it if the PC isn't always on.

### 3. Trust the developer profile (one time, on the iPhone)
After install, the first launch shows **"Untrusted Developer"**. Fix it once:
- iPhone **Settings → General → VPN & Device Management** → under **Developer App**, tap your Apple
  ID → **Trust "…"** → **Trust**.
- Now open **Covenant Path** from the home screen. Done.

---

## The 7-day expiry (and how to live with it)

A free Apple ID signs apps for **7 days**; after that the app won't launch until you re-sign it:
- **Sideloadly**: just run it again with the phone plugged in (same steps, ~1 minute).
- **AltStore/SideStore**: tap **Refresh** in the app (or it auto-refreshes over Wi-Fi). No re-download.

You can re-sign **before** it expires anytime — it resets the 7 days. A free account is limited to
**3 sideloaded apps** at once and re-signing about **10 apps/week**, neither of which you'll hit with
one app.

**When this becomes Ken's everyday app** (not just testing), the 7-day churn is annoying. The
permanent fixes, in order of cost: a paid **Apple Developer account** ($99/yr) → TestFlight (90-day
builds, up to 10,000 testers, installs from the App Store TestFlight app, no cable) or an ad-hoc
signed `.ipa` that lasts a year. Until then, weekly re-sign is the free path.

---

## Android (for comparison — much simpler)
No account, no expiry. From **Actions → "Build native Android (PoC)"**, download
**`covenant-path-native-android-debug`** → it's an `app-debug.apk`. Email/transfer it to the phone,
tap it, allow "install from this source", done. It just works and doesn't expire.

---

## What the app does that the website can't

The whole point of the native apps (and why sideloading is worth it): **"Sign in on the Church
website"** opens the real `churchofjesuschrist.org` login *inside the app*. The leader's password is
autofilled (Face ID / fingerprint unlocks the keychain) or typed **on the Church's own page** — never
in our app, never on our server — with the **full Church MFA** (text / email / authenticator). The app
captures only the resulting session. The web app can't do this (a browser can't read the Church's
cookies), which is exactly why this lane is mobile-only. See `native/PARITY.md` (2026-06-13).
