# Member Tools — Android live-traffic capture: runbook & learnings

*Performed 2026-06-13. Companion to `MEMBER_TOOLS_API_PROFILE.md` (the findings live there, §8).*

## Goal & why Android
Profile the **live** API calls the Member Tools app makes (to find endpoints not in our
`lcr_client`, e.g. a patriarchal-blessing source). The **macOS** app is **Apple-Silicon-only**, so it
can't run on an Intel/QEMU VM — but the **Android** app hits the **same backend**
(`membertools-api.churchofjesuschrist.org` + Okta), so we ran that instead, on the Android emulator,
behind mitmproxy.

## Environment
- adb `C:\platform-tools\adb.exe`; SDK `%LOCALAPPDATA%\Android\Sdk`; AVD **`Pixel_10`**
  (`google_apis_playstore`, x86_64, Android 36; abilist `x86_64,arm64-v8a`).
- Working dir **`E:\android-probe\`** holds: portable Temurin 17 JDK, mitmproxy standalone 12.2.3,
  `apktool.jar` 3.0.2, ADBKeyboard.apk, the APKs, `mitmconf/` (CA), `flows*.mitm`, helper scripts
  (`analyze_flows.py`, `dump_mt.py`).

## Pipeline (what worked)
1. **mitmproxy**: standalone Windows zip (NOT pip — mitmproxy 12 needs Python ≥3.12; box has 3.10).
   Run: `mitmdump --listen-host 127.0.0.1 -p 8080 --set confdir=E:\android-probe\mitmconf -w flows.mitm`.
2. **APK**: don't fight ABIs. Install Member Tools from the **Play Store on the Play-image AVD**, then
   `adb shell pm path org.lds.ldstools` → `adb pull` the device-matched splits (base + `config.x86_64`
   + `config.xxhdpi`). (Direct APKPure download gave armeabi_v7a-only — won't install on a 64-bit-only
   emulator; the "universal" APK had **no** native libs and the app needs `libsqlcipher.so` → crash.)
3. **Defeat pinning** with **apk-mitm**: zip the pulled splits into a `.xapk` **with a `manifest.json`**
   (`{package_name, split_apks:[{file,id}]}`), then
   `npx apk-mitm app.xapk --apktool E:\android-probe\apktool.jar --certificate mitmproxy-ca-cert.pem`.
   - `--apktool` with **apktool 3.0.2** is required (bundled 2.9.3 can't rebuild an SDK-36 app —
     `android:defaultLocale` link error).
   - `--certificate` must be **`.pem`/`.der`** (not `.cer`); it **injects our CA into the app's
     network-security-config**, so no device cert install is needed.
4. **Install + route**: `adb install-multiple <patched splits>`;
   `adb shell settings put global http_proxy 10.0.2.2:8080` (10.0.2.2 = host loopback).
5. **Log in** (Chrome Custom Tab + Okta): kept proxy **off** for login (Chrome doesn't trust our CA).
   Drove it with `adb shell input` using **`uiautomator dump` coordinates**; email-OTP 2nd factor read
   from the connected **Gmail**. The final Custom-Tab→app redirect needed **one human tap** (see
   learnings). Then flip proxy **on** (the patched app trusts our CA → decrypts).
6. **Navigate + capture**: set the app PIN, open Directory → a member; mitmdump records to `flows.mitm`.
7. **Analyze**: `mitmdump -nr flows.mitm -s analyze_flows.py` (unique endpoints) and `dump_mt.py`
   (full request/response detail for the MT/push hosts).

## Learnings / gotchas (the reusable bits)
- **mitmproxy 12 ⇒ Python ≥3.12.** On 3.10, use the **standalone binaries**, not `pip`.
- **Emulator ABIs:** modern x86_64 images are `x86_64,arm64-v8a` (no 32-bit ARM). Get an
  ABI-matched build by **Play-install → pull splits**, not random APK mirrors.
- **apk-mitm on new apps:** pass a current **`--apktool`** jar; hand-built bundles need
  **`manifest.json`**; **`--certificate .pem`** injects the CA (skips the device cert-install dance).
- **Resigning is fine:** debug-key resign didn't break the app, its custom-scheme handler, or login —
  the API doesn't gate on app signature / Play Integrity.
- **Typing into the app:** `adb shell input text` works on Chrome web fields and handles specials if
  single-quoted on the **device** shell: `adb shell "input text 'F@m\$ly`60'"`. **ADBKeyboard's
  broadcast does NOT reach Chrome web fields** (works only for native fields).
- **Tapping:** never guess pixels — **`uiautomator dump`** gives exact `bounds`; tap centers. (This was
  the single biggest reliability win.)
- **MFA:** the account's **email OTP** lands in Gmail and is readable via the connected Gmail tool →
  automatable 2nd factor.
- **The one un-scriptable step:** Okta's `com.okta.webauthenticationui` Custom-Tab redirect to
  `membertoolsauth://login` is **blocked by Chrome without a user gesture**, and the success
  interstitial then **times the sign-in session out**. Needs a real tap (or proxy+device-CA to capture
  the `code` and fire the intent manually).
- **Data model:** post-sync the app reads from a **local SQLCipher DB**; per-member navigation makes
  **no** network calls. Endpoint discovery = the **sync/login/push** calls, not per-screen taps.
- **Google/Firebase** services pin certs → TLS fails through the proxy. Expected; ignore them.

## Results
See **`MEMBER_TOOLS_API_PROFILE.md` §8** — 3 endpoints beyond our client
(`POST /api/v5/sync/files` → photos ZIP via `Accept: application/zip`; `GET /api/v5/user`; push
registration), and **patriarchal blessing confirmed absent from Member Tools** (LCR-only).

## Teardown (done 2026-06-13)
`adb shell settings delete global http_proxy` · `adb emu kill` · stop `mitmdump`. The `E:\android-probe`
working set (incl. the 65 MB decrypted capture with real member data/photos) is local-only — delete if
not needed.
