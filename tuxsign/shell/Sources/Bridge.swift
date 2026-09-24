import AVFoundation
import CoreLocation
import CoreMotion
import LocalAuthentication
import SwiftUI
import UIKit
import UserNotifications
import WebKit

/// JavaScript <-> native bridge.
///   JS:  await tux.call("motion.start", { hz: 60 })
///        window.addEventListener("tux:motion", e => e.detail.accel.x)
@MainActor
final class Bridge: NSObject, WKScriptMessageHandlerWithReply, CLLocationManagerDelegate {
    weak var webView: WKWebView?
    weak var state: ShellState?

    private let motion = CMMotionManager()
    private let altimeter = CMAltimeter()
    private let pedometer = CMPedometer()
    private let location = CLLocationManager()
    private var recorder: AVAudioRecorder?
    private var micTimer: Timer?

    /// The `tux` API object, shared by web pages and native (JavaScriptCore) apps.
    static let apiJS = """
    function __tuxAPI(post, on) {
      return {
        native: true,
        call: post,
        on,
        device: { info: () => post('device.info'), battery: () => post('device.battery') },
        motion: { start: (hz) => post('motion.start', { hz }), stop: () => post('motion.stop') },
        altimeter: { start: () => post('altimeter.start'), stop: () => post('altimeter.stop') },
        pedometer: { start: () => post('pedometer.start'), stop: () => post('pedometer.stop') },
        location: { start: () => post('location.start'), stop: () => post('location.stop') },
        proximity: { start: () => post('proximity.start'), stop: () => post('proximity.stop') },
        mic: { start: () => post('mic.start'), stop: () => post('mic.stop') },
        haptic: (style) => post('haptic', { style }),
        torch: (on) => post('torch', { on }),
        biometric: (reason) => post('biometric', { reason }),
        share: (text, url) => post('share', { text, url }),
        speak: (text, opts) => post('speak', Object.assign({ text }, opts || {})),
        notify: (title, body, delay) => post('notify', { title, body, delay }),
        clipboard: { write: (text) => post('clipboard.write', { text }), read: () => post('clipboard.read') },
        open: (url) => post('open', { url }),
        ui: {
          setToolbar: (items, tint) => post('ui.toolbar', { items, tint }),
          statusBar: (style) => post('ui.statusBar', { style }),
        },
      };
    }
    """

    static let javascript = apiJS + """
    (() => {
      const post = (method, args) => window.webkit.messageHandlers.tux.postMessage({ method, args: args || {} });
      const on = (name, fn) => { const h = e => fn(e.detail); window.addEventListener('tux:' + name, h); return () => window.removeEventListener('tux:' + name, h); };
      window.tux = __tuxAPI(post, on);
      window.dispatchEvent(new Event('tuxready'));
    })();
    """

    /// When set (native mode), events go here instead of to the web view.
    var sink: ((String, Any) -> Void)?
    private let speech = AVSpeechSynthesizer()

    func emit(_ event: String, _ payload: Any) {
        if let sink { sink(event, payload); return }
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else { return }
        webView?.evaluateJavaScript("window.dispatchEvent(new CustomEvent('tux:\(event)', { detail: \(json) }))")
    }

    func userContentController(_ controller: WKUserContentController,
                               didReceive message: WKScriptMessage) async -> (Any?, String?) {
        guard let body = message.body as? [String: Any], let method = body["method"] as? String else {
            return (nil, "bad message")
        }
        let args = body["args"] as? [String: Any] ?? [:]
        do {
            return (try await handle(method, args), nil)
        } catch {
            return (nil, error.localizedDescription)
        }
    }

    struct BridgeError: LocalizedError {
        let errorDescription: String?
        init(_ msg: String) { errorDescription = msg }
    }

    func handle(_ method: String, _ args: [String: Any]) async throws -> Any? {
        switch method {
        case "device.info":
            let d = UIDevice.current
            return ["name": d.name, "model": d.model, "system": d.systemName, "version": d.systemVersion,
                    "idiom": d.userInterfaceIdiom == .pad ? "pad" : "phone",
                    "sensors": ["accelerometer": motion.isAccelerometerAvailable, "gyroscope": motion.isGyroAvailable,
                                "magnetometer": motion.isMagnetometerAvailable,
                                "barometer": CMAltimeter.isRelativeAltitudeAvailable(),
                                "pedometer": CMPedometer.isStepCountingAvailable(),
                                "compass": CLLocationManager.headingAvailable()]]
        case "device.battery":
            UIDevice.current.isBatteryMonitoringEnabled = true
            let s = UIDevice.current.batteryState
            return ["level": UIDevice.current.batteryLevel, "charging": s == .charging || s == .full,
                    "lowPower": ProcessInfo.processInfo.isLowPowerModeEnabled]

        case "motion.start":
            let hz = (args["hz"] as? Double) ?? 60
            motion.deviceMotionUpdateInterval = 1 / hz
            motion.magnetometerUpdateInterval = 1 / hz
            motion.startMagnetometerUpdates()
            motion.startDeviceMotionUpdates(using: .xArbitraryCorrectedZVertical, to: .main) { [weak self] m, _ in
                guard let self, let m else { return }
                let mag = self.motion.magnetometerData?.magneticField
                let a = m.userAcceleration, g = m.gravity, r = m.rotationRate, at = m.attitude
                self.emit("motion", [
                    "accel": ["x": a.x + g.x, "y": a.y + g.y, "z": a.z + g.z],
                    "userAccel": ["x": a.x, "y": a.y, "z": a.z],
                    "gravity": ["x": g.x, "y": g.y, "z": g.z],
                    "gyro": ["x": r.x, "y": r.y, "z": r.z],
                    "magnet": ["x": mag?.x ?? 0, "y": mag?.y ?? 0, "z": mag?.z ?? 0],
                    "attitude": ["roll": at.roll, "pitch": at.pitch, "yaw": at.yaw],
                    "t": m.timestamp,
                ])
            }
            return true
        case "motion.stop":
            motion.stopDeviceMotionUpdates(); motion.stopMagnetometerUpdates(); return true

        case "altimeter.start":
            guard CMAltimeter.isRelativeAltitudeAvailable() else { throw BridgeError("barometer unavailable") }
            altimeter.startRelativeAltitudeUpdates(to: .main) { [weak self] d, _ in
                guard let d else { return }
                self?.emit("altimeter", ["pressureKPa": d.pressure.doubleValue, "relativeAltitude": d.relativeAltitude.doubleValue])
            }
            return true
        case "altimeter.stop":
            altimeter.stopRelativeAltitudeUpdates(); return true

        case "pedometer.start":
            guard CMPedometer.isStepCountingAvailable() else { throw BridgeError("pedometer unavailable") }
            pedometer.startUpdates(from: Calendar.current.startOfDay(for: .now)) { [weak self] d, _ in
                guard let d else { return }
                let steps = d.numberOfSteps.intValue, dist = d.distance?.doubleValue ?? 0
                Task { @MainActor in self?.emit("pedometer", ["steps": steps, "distance": dist]) }
            }
            return true
        case "pedometer.stop":
            pedometer.stopUpdates(); return true

        case "location.start":
            location.delegate = self
            location.desiredAccuracy = kCLLocationAccuracyBest
            location.requestWhenInUseAuthorization()
            location.startUpdatingLocation()
            location.startUpdatingHeading()
            return true
        case "location.stop":
            location.stopUpdatingLocation(); location.stopUpdatingHeading(); return true

        case "proximity.start":
            UIDevice.current.isProximityMonitoringEnabled = true
            NotificationCenter.default.addObserver(self, selector: #selector(proximityChanged),
                                                   name: UIDevice.proximityStateDidChangeNotification, object: nil)
            return UIDevice.current.isProximityMonitoringEnabled
        case "proximity.stop":
            UIDevice.current.isProximityMonitoringEnabled = false; return true

        case "mic.start":
            guard await AVAudioApplication.requestRecordPermission() else { throw BridgeError("microphone denied") }
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, options: [.mixWithOthers, .defaultToSpeaker])
            try session.setActive(true)
            recorder = try AVAudioRecorder(url: URL(fileURLWithPath: "/dev/null"), settings: [
                AVFormatIDKey: kAudioFormatAppleLossless, AVSampleRateKey: 44100, AVNumberOfChannelsKey: 1])
            recorder?.isMeteringEnabled = true
            recorder?.record()
            micTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    guard let r = self?.recorder else { return }
                    r.updateMeters()
                    self?.emit("mic", ["average": r.averagePower(forChannel: 0), "peak": r.peakPower(forChannel: 0)])
                }
            }
            return true
        case "mic.stop":
            micTimer?.invalidate(); recorder?.stop(); recorder = nil; return true

        case "haptic":
            switch args["style"] as? String ?? "medium" {
            case "success": UINotificationFeedbackGenerator().notificationOccurred(.success)
            case "warning": UINotificationFeedbackGenerator().notificationOccurred(.warning)
            case "error": UINotificationFeedbackGenerator().notificationOccurred(.error)
            case "selection": UISelectionFeedbackGenerator().selectionChanged()
            case "light": UIImpactFeedbackGenerator(style: .light).impactOccurred()
            case "heavy": UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
            case "rigid": UIImpactFeedbackGenerator(style: .rigid).impactOccurred()
            case "soft": UIImpactFeedbackGenerator(style: .soft).impactOccurred()
            default: UIImpactFeedbackGenerator(style: .medium).impactOccurred()
            }
            return true

        case "torch":
            guard let dev = AVCaptureDevice.default(for: .video), dev.hasTorch else { throw BridgeError("no torch") }
            try dev.lockForConfiguration()
            dev.torchMode = (args["on"] as? Bool ?? true) ? .on : .off
            dev.unlockForConfiguration()
            return true

        case "biometric":
            let ctx = LAContext()
            var err: NSError?
            guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &err) else {
                throw BridgeError(err?.localizedDescription ?? "biometrics unavailable")
            }
            let ok = try await ctx.evaluatePolicy(.deviceOwnerAuthentication,
                                                  localizedReason: args["reason"] as? String ?? "Authenticate")
            return ["success": ok, "type": ctx.biometryType == .faceID ? "faceID" : ctx.biometryType == .touchID ? "touchID" : "passcode"]

        case "share":
            var items: [Any] = []
            if let t = args["text"] as? String { items.append(t) }
            if let u = (args["url"] as? String).flatMap(URL.init(string:)) { items.append(u) }
            let vc = UIActivityViewController(activityItems: items, applicationActivities: nil)
            let top = Self.topViewController()
            vc.popoverPresentationController?.sourceView = top?.view
            top?.present(vc, animated: true)
            return true

        case "speak":
            let utterance = AVSpeechUtterance(string: args["text"] as? String ?? "")
            if let lang = args["language"] as? String { utterance.voice = AVSpeechSynthesisVoice(language: lang) }
            if let rate = args["rate"] as? Double { utterance.rate = Float(rate) }
            if let pitch = args["pitch"] as? Double { utterance.pitchMultiplier = Float(pitch) }
            speech.speak(utterance)
            return true

        case "notify":
            let center = UNUserNotificationCenter.current()
            guard try await center.requestAuthorization(options: [.alert, .sound, .badge]) else {
                throw BridgeError("notifications denied")
            }
            let content = UNMutableNotificationContent()
            content.title = args["title"] as? String ?? ""
            content.body = args["body"] as? String ?? ""
            content.sound = .default
            let trigger = UNTimeIntervalNotificationTrigger(timeInterval: max(1, args["delay"] as? Double ?? 1), repeats: false)
            try await center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: trigger))
            return true

        case "clipboard.write":
            UIPasteboard.general.string = args["text"] as? String; return true
        case "clipboard.read":
            return UIPasteboard.general.string

        case "open":
            guard let u = (args["url"] as? String).flatMap(URL.init(string:)) else { throw BridgeError("bad url") }
            return await UIApplication.shared.open(u)

        case "ui.toolbar":
            let items = (args["items"] as? [[String: Any]] ?? []).compactMap { d -> ToolbarItemSpec? in
                guard let id = d["id"] as? String, let icon = d["icon"] as? String else { return nil }
                return ToolbarItemSpec(id: id, icon: icon, title: d["title"] as? String)
            }
            state?.toolbar = items
            state?.tint = (args["tint"] as? String).flatMap(Color.init(hex:))
            return true
        case "ui.statusBar":
            Self.topViewController()?.view.window?.overrideUserInterfaceStyle = (args["style"] as? String) == "light" ? .dark : .light
            return true

        default:
            throw BridgeError("unknown method \(method)")
        }
    }

    static func topViewController() -> UIViewController? {
        let window = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.keyWindow }.first
        var top = window?.rootViewController
        while let presented = top?.presentedViewController { top = presented }
        return top
    }

    @objc private func proximityChanged() {
        emit("proximity", ["near": UIDevice.current.proximityState])
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let l = locations.last else { return }
        let payload: [String: Double] = [
            "latitude": l.coordinate.latitude, "longitude": l.coordinate.longitude, "altitude": l.altitude,
            "accuracy": l.horizontalAccuracy, "speed": l.speed, "course": l.course,
        ]
        Task { @MainActor in self.emit("location", payload) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateHeading h: CLHeading) {
        let payload = ["magnetic": h.magneticHeading, "true": h.trueHeading, "accuracy": h.headingAccuracy]
        Task { @MainActor in self.emit("heading", payload) }
    }
}

extension Color {
    init?(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6 || s.count == 8, let v = UInt64(s, radix: 16) else { return nil }
        let rgb = s.count == 8 ? v >> 8 : v
        let alpha = s.count == 8 ? Double(v & 0xFF) / 255 : 1
        self.init(red: Double((rgb >> 16) & 0xFF) / 255, green: Double((rgb >> 8) & 0xFF) / 255,
                  blue: Double(rgb & 0xFF) / 255, opacity: alpha)
    }
}
