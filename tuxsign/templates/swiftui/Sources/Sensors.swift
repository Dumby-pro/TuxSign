import AVFoundation
import CoreLocation
import CoreMotion
import LocalAuthentication
import SwiftUI
import UIKit

/// One observable object that drives every sensor on the device.
@MainActor
@Observable
final class Sensors: NSObject, CLLocationManagerDelegate {
    // Motion
    var acceleration = CMAcceleration()
    var rotation = CMRotationRate()
    var magnetic = CMMagneticField()
    var attitude = (roll: 0.0, pitch: 0.0, yaw: 0.0)
    var gravity = CMAcceleration()
    // Environment
    var pressureKPa: Double?
    var relativeAltitude: Double?
    var steps: Int?
    var location: CLLocation?
    var heading: CLHeading?
    var soundLevel: Float = -160
    // Device state
    var proximityNear = false
    var batteryLevel: Float = -1
    var batteryState = UIDevice.BatteryState.unknown
    var thermal = ProcessInfo.processInfo.thermalState
    var brightness = 0.0
    var authResult: String?

    private let motion = CMMotionManager()
    private let altimeter = CMAltimeter()
    private let pedometer = CMPedometer()
    private let locationManager = CLLocationManager()
    private var recorder: AVAudioRecorder?
    private var timer: Timer?

    var available: [String: Bool] {
        [
            "Accelerometer": motion.isAccelerometerAvailable,
            "Gyroscope": motion.isGyroAvailable,
            "Magnetometer": motion.isMagnetometerAvailable,
            "Device motion": motion.isDeviceMotionAvailable,
            "Barometer": CMAltimeter.isRelativeAltitudeAvailable(),
            "Pedometer": CMPedometer.isStepCountingAvailable(),
            "Compass": CLLocationManager.headingAvailable(),
        ]
    }

    func start() {
        let interval = 1.0 / 60.0
        motion.accelerometerUpdateInterval = interval
        motion.gyroUpdateInterval = interval
        motion.magnetometerUpdateInterval = interval
        motion.deviceMotionUpdateInterval = interval

        motion.startAccelerometerUpdates(to: .main) { [weak self] d, _ in
            if let d { self?.acceleration = d.acceleration }
        }
        motion.startGyroUpdates(to: .main) { [weak self] d, _ in
            if let d { self?.rotation = d.rotationRate }
        }
        motion.startMagnetometerUpdates(to: .main) { [weak self] d, _ in
            if let d { self?.magnetic = d.magneticField }
        }
        motion.startDeviceMotionUpdates(to: .main) { [weak self] d, _ in
            guard let d else { return }
            self?.attitude = (d.attitude.roll, d.attitude.pitch, d.attitude.yaw)
            self?.gravity = d.gravity
        }
        if CMAltimeter.isRelativeAltitudeAvailable() {
            altimeter.startRelativeAltitudeUpdates(to: .main) { [weak self] d, _ in
                guard let d else { return }
                self?.pressureKPa = d.pressure.doubleValue
                self?.relativeAltitude = d.relativeAltitude.doubleValue
            }
        }
        if CMPedometer.isStepCountingAvailable() {
            pedometer.startUpdates(from: Calendar.current.startOfDay(for: .now)) { [weak self] d, _ in
                let n = d?.numberOfSteps.intValue
                Task { @MainActor in self?.steps = n }
            }
        }

        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.requestWhenInUseAuthorization()
        locationManager.startUpdatingLocation()
        locationManager.startUpdatingHeading()

        let device = UIDevice.current
        device.isProximityMonitoringEnabled = true
        device.isBatteryMonitoringEnabled = true

        startMicrophone()

        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.poll() }
        }
    }

    func stop() {
        motion.stopAccelerometerUpdates()
        motion.stopGyroUpdates()
        motion.stopMagnetometerUpdates()
        motion.stopDeviceMotionUpdates()
        altimeter.stopRelativeAltitudeUpdates()
        pedometer.stopUpdates()
        locationManager.stopUpdatingLocation()
        locationManager.stopUpdatingHeading()
        UIDevice.current.isProximityMonitoringEnabled = false
        recorder?.stop()
        recorder = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        timer?.invalidate()
    }

    private func poll() {
        let device = UIDevice.current
        proximityNear = device.proximityState
        batteryLevel = device.batteryLevel
        batteryState = device.batteryState
        thermal = ProcessInfo.processInfo.thermalState
        if let screen = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.screen {
            brightness = screen.brightness
        }
        recorder?.updateMeters()
        soundLevel = recorder?.averagePower(forChannel: 0) ?? -160
    }

    private func startMicrophone() {
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            guard granted else { return }
            Task { @MainActor in
                let session = AVAudioSession.sharedInstance()
                try? session.setCategory(.playAndRecord, options: [.mixWithOthers, .defaultToSpeaker])
                // iOS mutes haptics while recording unless the app opts back in.
                try? session.setAllowHapticsAndSystemSoundsDuringRecording(true)
                try? session.setActive(true)
                let url = URL(fileURLWithPath: "/dev/null")
                let settings: [String: Any] = [AVFormatIDKey: kAudioFormatAppleLossless,
                                               AVSampleRateKey: 44100, AVNumberOfChannelsKey: 1]
                self?.recorder = try? AVAudioRecorder(url: url, settings: settings)
                self?.recorder?.isMeteringEnabled = true
                self?.recorder?.record()
            }
        }
    }

    func authenticate() {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            authResult = error?.localizedDescription ?? "Unavailable"
            return
        }
        context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Unlock sensors") { ok, err in
            Task { @MainActor in self.authResult = ok ? "Authenticated ✓" : (err?.localizedDescription ?? "Failed") }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let last = locations.last
        Task { @MainActor in self.location = last }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateHeading newHeading: CLHeading) {
        Task { @MainActor in self.heading = newHeading }
    }
}
