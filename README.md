# TuxSign

Build, package, sign and install iOS apps **from Linux**.

- **SwiftUI apps** with iOS 26 **Liquid Glass** (`glassEffect`, `GlassEffectContainer`, `.buttonStyle(.glass)`, morphing, minimizing tab bar)
- **HTML apps** that run inside a native shell, with a JavaScript bridge to every sensor and a native Liquid Glass toolbar
- **Sensors**: accelerometer, gyroscope, magnetometer, attitude, barometer/altimeter, pedometer, GPS, compass, proximity, microphone level, camera + torch, battery/thermal, Face ID/Touch ID, haptics
- **Signing** with a `.p12` certificate and a `.mobileprovision` profile (through `zsign` or `rcodesign`)
- **Install** over USB or Wi-Fi with libimobiledevice
- **Cloud builds**: every project ships a GitHub Actions workflow that builds the IPA on a Mac runner, so you never need a Mac

## Install

```sh
pip install git+https://github.com/Dumby-pro/TuxSign
tuxsign doctor        # shows which optional tools are missing
```

Optional tools: `zsign` or `rcodesign` for signing, and `libimobiledevice-utils` + `ideviceinstaller` for installing on a device. To compile Swift locally you also need `swiftc`, `lld` and an iOS SDK.

## Quick start

```sh
tuxsign new MyApp                 # SwiftUI + Liquid Glass + sensor dashboard
tuxsign new MyWeb -t html         # HTML/CSS/JS app with the native sensor bridge
cd MyApp
tuxsign build                     # → build/MyApp.ipa (unsigned)
tuxsign sign build/MyApp.ipa -c dev.p12 -m dev.mobileprovision
tuxsign install build/MyApp-signed.ipa
# or all at once:
tuxsign run -c dev.p12 -m dev.mobileprovision --log
```

### How builds work

| Project | Linux with SDK | Linux without SDK | GitHub Actions (`macos-26`) |
|---|---|---|---|
| SwiftUI | `swiftc` + `ld64.lld` | ✗ (use cloud) | ✓ |
| HTML | compiles the shell | ✓ uses the prebuilt **TuxShell** | ✓ |

- **Cloud build:** push the project to GitHub, open **Actions → Build IPA**, then download the `*-ipa` artifact and sign it with `tuxsign sign`.
- **Local SDK:** copy `iPhoneOS.sdk` from any Xcode 26 install, then run `tuxsign sdk add path/to/iPhoneOS.sdk`.
- **HTML apps without an SDK:** TuxSign downloads the prebuilt shell from this repo's releases, which CI builds. It then copies in your `www/` folder and writes the Info.plist. Nothing gets compiled. You can also run `tuxsign shell add TuxShell.app.zip`.

## Liquid Glass for HTML (TuxGlass)

New HTML projects include `tux-glass.js` and `tux-glass.css`, which bring Liquid Glass to web content:

- **Lensing:** content is bent at the curved rim. The displacement map is calculated from a convex rim profile using Snell's law (IOR 1.5).
- **Chromatic dispersion:** a three-channel pass adds the faint colour fringe at the edges.
- **Specular rim:** the highlight catches the light on one side and the opposite edge, and follows device tilt (`TuxGlass.followTilt()`).
- **Interactive glass:** `glass-interactive` elements flex toward your finger, grow, glow from the touch point and lens more strongly while pressed.
- **Materialize:** `TuxGlass.show(el)` / `TuxGlass.hide(el)` animate the lensing in and out.
- **Variants:** regular, `glass-clear`, `glass-dark` and `data-glass-tint="..."`. Dark mode and Reduce Transparency are supported.

```html
<div class="glass-backdrop"></div>                     <!-- the wallpaper glass refracts -->
<div class="glass">Card</div>
<button class="glass glass-interactive">Tap me</button>
<nav class="glass" data-glass-source=".glass-backdrop, main">…</nav>  <!-- also refracts scrolling content -->
```

Tuning, per element or as CSS variables: `data-glass-thickness`, `-bezel`, `-ior`, `-frost`, `-dispersion`, `-saturation`.

How it works: WebKit, the engine inside iOS apps, can't apply SVG filters to `backdrop-filter`. So TuxGlass copies each glass element's source (`.glass-backdrop` by default) into that element and refracts the copy with an SVG displacement filter. Two things follow from that:
- **Only listed sources are refracted.** Glass bends only what its source list contains. Add more selectors with `data-glass-source`.
- **Don't set `transform` on `.glass` elements.** TuxGlass uses it for animation. Use `translate`, `left` or `top` instead.

## HTML bridge

```js
await tux.motion.start(60);
tux.on('motion', m => console.log(m.accel, m.gyro, m.magnet, m.attitude));
await tux.location.start();      tux.on('location', l => ...); tux.on('heading', h => ...);
await tux.altimeter.start();     tux.on('altimeter', a => a.pressureKPa);
await tux.pedometer.start();     tux.on('pedometer', p => p.steps);
await tux.proximity.start();     tux.on('proximity', p => p.near);
await tux.mic.start();           tux.on('mic', m => m.average);
await tux.biometric('Unlock');   // Face ID / Touch ID
tux.haptic('success'); tux.torch(true); tux.share('hi'); tux.device.battery();
// real Liquid Glass buttons over your page:
tux.ui.setToolbar([{ id: 'add', icon: 'plus', title: 'Add' }], '#0a84ff');
tux.on('toolbar', ({ id }) => ...);
```

Run `tuxsign serve` to preview the page in a desktop browser.

## Commands

`new`, `build`, `sign`, `install`, `run`, `inspect` (for .ipa, .mobileprovision or .p12 files), `devices`, `sdk add|list`, `shell add|path`, `serve`, `doctor`

## Certificates

TuxSign signs with a certificate and provisioning profile you already have. It does not log in to Apple accounts. Here's how to get the files:
- **Paid developer account:** download them from developer.apple.com. Create the certificate from a CSR, which you can make with `openssl req`.
- **Free account:** create them once in Xcode, or with a dedicated sideloading tool. Then export the certificate as a `.p12`.

The `.p12` password can come from `-p`, from `$TUXSIGN_P12_PASSWORD`, or from a prompt.
