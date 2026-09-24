import AVFoundation
import SwiftUI

struct SensorsView: View {
    @State private var sensors = Sensors()

    var body: some View {
        ScrollView {
            GlassEffectContainer(spacing: 16) {
                VStack(spacing: 16) {
                    card("Accelerometer (g)", "move.3d") {
                        xyz(sensors.acceleration.x, sensors.acceleration.y, sensors.acceleration.z)
                    }
                    card("Gyroscope (rad/s)", "gyroscope") {
                        xyz(sensors.rotation.x, sensors.rotation.y, sensors.rotation.z)
                    }
                    card("Magnetometer (µT)", "dot.radiowaves.left.and.right") {
                        xyz(sensors.magnetic.x, sensors.magnetic.y, sensors.magnetic.z)
                    }
                    card("Attitude (°)", "rotate.3d") {
                        row("Roll", deg(sensors.attitude.roll))
                        row("Pitch", deg(sensors.attitude.pitch))
                        row("Yaw", deg(sensors.attitude.yaw))
                    }
                    card("Barometer", "barometer") {
                        row("Pressure", sensors.pressureKPa.map { String(format: "%.2f kPa", $0) } ?? "–")
                        row("Rel. altitude", sensors.relativeAltitude.map { String(format: "%.2f m", $0) } ?? "–")
                    }
                    card("Location & Compass", "location.north.line") {
                        row("Lat", sensors.location.map { String(format: "%.5f", $0.coordinate.latitude) } ?? "–")
                        row("Lon", sensors.location.map { String(format: "%.5f", $0.coordinate.longitude) } ?? "–")
                        row("Altitude", sensors.location.map { String(format: "%.1f m", $0.altitude) } ?? "–")
                        row("Speed", sensors.location.map { String(format: "%.1f m/s", max(0, $0.speed)) } ?? "–")
                        row("Heading", sensors.heading.map { String(format: "%.0f°", $0.trueHeading) } ?? "–")
                    }
                    card("Activity", "figure.walk") {
                        row("Steps today", sensors.steps.map(String.init) ?? "–")
                    }
                    card("Microphone", "waveform") {
                        row("Level", String(format: "%.0f dBFS", sensors.soundLevel))
                        ProgressView(value: Double(max(0, sensors.soundLevel + 60) / 60))
                    }
                    card("Device", "iphone") {
                        row("Proximity", sensors.proximityNear ? "Near" : "Far")
                        row("Battery", sensors.batteryLevel < 0 ? "–" : "\(Int(sensors.batteryLevel * 100))%")
                        row("Charging", sensors.batteryState == .charging || sensors.batteryState == .full ? "Yes" : "No")
                        row("Thermal", "\(sensors.thermal)")
                        row("Brightness", String(format: "%.0f%%", sensors.brightness * 100))
                    }
                    card("Biometrics", "faceid") {
                        Button("Authenticate") { sensors.authenticate() }
                            .buttonStyle(.glassProminent)
                        if let r = sensors.authResult { Text(r).font(.footnote) }
                    }
                    card("Availability", "checklist") {
                        ForEach(sensors.available.sorted(by: { $0.key < $1.key }), id: \.key) { item in
                            row(item.key, item.value ? "✓" : "✗")
                        }
                    }
                }
                .padding()
            }
        }
        .background(LinearGradient(colors: [.teal, .blue, .indigo], startPoint: .top, endPoint: .bottom).ignoresSafeArea())
        .navigationTitle("Sensors")
        .onAppear { sensors.start() }
        .onDisappear { sensors.stop() }
    }

    private func card<Content: View>(_ title: String, _ icon: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: icon).font(.headline)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .glassEffect(.regular, in: .rect(cornerRadius: 24))
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack { Text(k).foregroundStyle(.secondary); Spacer(); Text(v).monospacedDigit() }
    }

    private func xyz(_ x: Double, _ y: Double, _ z: Double) -> some View {
        VStack {
            row("X", String(format: "%+.3f", x))
            row("Y", String(format: "%+.3f", y))
            row("Z", String(format: "%+.3f", z))
        }
    }

    private func deg(_ r: Double) -> String { String(format: "%+.1f", r * 180 / .pi) }
}

// MARK: - Camera

struct CameraView: View {
    @State private var camera = Camera()

    var body: some View {
        ZStack(alignment: .bottom) {
            CameraPreview(session: camera.session).ignoresSafeArea()
            HStack(spacing: 20) {
                Button { camera.flip() } label: { Image(systemName: "arrow.triangle.2.circlepath.camera") }
                Button { camera.toggleTorch() } label: { Image(systemName: camera.torchOn ? "flashlight.on.fill" : "flashlight.off.fill") }
            }
            .font(.title2)
            .buttonStyle(.glass)
            .padding(.bottom, 40)
        }
        .onAppear { camera.start() }
        .onDisappear { camera.stop() }
    }
}

@Observable
final class Camera {
    let session = AVCaptureSession()
    var torchOn = false
    private var position: AVCaptureDevice.Position = .back
    private let queue = DispatchQueue(label: "camera")

    func start() {
        AVCaptureDevice.requestAccess(for: .video) { granted in
            guard granted else { return }
            self.queue.async { self.configure(); self.session.startRunning() }
        }
    }

    func stop() { queue.async { self.session.stopRunning() } }

    func flip() {
        position = position == .back ? .front : .back
        queue.async { self.configure() }
    }

    func toggleTorch() {
        guard let device = AVCaptureDevice.default(for: .video), device.hasTorch else { return }
        try? device.lockForConfiguration()
        device.torchMode = device.torchMode == .on ? .off : .on
        torchOn = device.torchMode == .on
        device.unlockForConfiguration()
    }

    private func configure() {
        session.beginConfiguration()
        session.inputs.forEach(session.removeInput)
        if let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: position),
           let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) {
            session.addInput(input)
        }
        session.commitConfiguration()
    }
}

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {}
}
