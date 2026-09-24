// {{NAME}} - talks to native sensors through window.tux (injected by TuxShell).
// Also runs in a desktop browser with fallbacks, so you can develop with
// `tuxsign serve` and test in Chrome/Firefox first.

const $ = (id) => document.getElementById(id);
const fmt = (v, d = 3) => (typeof v === 'number' ? v.toFixed(d) : '–');
const grid = (el, rows) => { el.innerHTML = Object.entries(rows).map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join(''); };

async function main() {
  if (!window.tux) {
    $('device').textContent = 'Browser preview (native sensors run on iPhone)';
    window.addEventListener('devicemotion', (e) => showMotion({ accel: { x: (e.accelerationIncludingGravity?.x || 0) / 9.81, y: (e.accelerationIncludingGravity?.y || 0) / 9.81, z: (e.accelerationIncludingGravity?.z || 0) / 9.81 } }));
    return;
  }

  const info = await tux.device.info();
  $('device').textContent = `${info.model} · iOS ${info.version}`;

  // Real Liquid Glass buttons, rendered natively over the page.
  await tux.ui.setToolbar([
    { id: 'top', icon: 'arrow.up' },
    { id: 'haptic', icon: 'hand.tap', title: 'Tap' },
    { id: 'share', icon: 'square.and.arrow.up' },
  ]);
  tux.on('toolbar', ({ id }) => {
    if (id === 'top') window.scrollTo({ top: 0, behavior: 'smooth' });
    if (id === 'haptic') tux.haptic('heavy');
    if (id === 'share') tux.share('Built on Linux with TuxSign');
  });

  tux.on('motion', showMotion);
  const loc = {};
  tux.on('location', (l) => { Object.assign(loc, { Lat: fmt(l.latitude, 5), Lon: fmt(l.longitude, 5), Altitude: fmt(l.altitude, 1) + ' m', Speed: fmt(Math.max(0, l.speed), 1) + ' m/s' }); grid($('location'), loc); });
  tux.on('heading', (h) => { loc.Heading = fmt(h.true, 0) + '°'; grid($('location'), loc); });
  const env = {};
  tux.on('altimeter', (a) => { env.Pressure = fmt(a.pressureKPa, 2) + ' kPa'; env['Rel. altitude'] = fmt(a.relativeAltitude, 2) + ' m'; grid($('env'), env); });
  tux.on('pedometer', (p) => { env.Steps = p.steps; grid($('env'), env); });
  tux.on('mic', (m) => { $('mic').value = m.average; });
  const dev = {};
  tux.on('proximity', (p) => { dev.Proximity = p.near ? 'Near' : 'Far'; grid($('dev'), dev); });

  await tux.motion.start(60);
  await tux.location.start();
  tux.altimeter.start().catch(() => {});
  tux.pedometer.start().catch(() => {});
  tux.proximity.start();
  tux.mic.start().catch(() => {});

  const b = await tux.device.battery();
  Object.assign(dev, { Battery: Math.round(b.level * 100) + '%', Charging: b.charging ? 'Yes' : 'No', 'Low power': b.lowPower ? 'On' : 'Off' });
  grid($('dev'), dev);

  document.querySelectorAll('[data-haptic]').forEach((el) => el.addEventListener('click', () => tux.haptic(el.dataset.haptic)));
  $('auth').onclick = async () => { try { const r = await tux.biometric('Unlock {{NAME}}'); $('auth').textContent = r.success ? '✓ ' + r.type : 'Failed'; } catch (e) { $('auth').textContent = e.message; } };
  let torch = false;
  $('torch').onclick = () => tux.torch((torch = !torch)).catch(() => {});
  $('share').onclick = () => tux.share('Built on Linux with TuxSign');
}

function showMotion(m) {
  const a = m.accel;
  const rows = { 'Accel X': fmt(a.x), 'Accel Y': fmt(a.y), 'Accel Z': fmt(a.z) };
  if (m.gyro) Object.assign(rows, { 'Gyro X': fmt(m.gyro.x), 'Gyro Y': fmt(m.gyro.y), 'Gyro Z': fmt(m.gyro.z) });
  if (m.magnet) Object.assign(rows, { 'Mag X': fmt(m.magnet.x, 1), 'Mag Y': fmt(m.magnet.y, 1), 'Mag Z': fmt(m.magnet.z, 1) });
  if (m.attitude) Object.assign(rows, { Roll: fmt(m.attitude.roll * 57.3, 1) + '°', Pitch: fmt(m.attitude.pitch * 57.3, 1) + '°' });
  grid($('motion'), rows);
  $('bubble').style.transform = `translate(${-a.x * 120}px, ${a.y * 60}px)`;
}

// TuxShell injects window.tux before any page script runs.
main();
