import JavaScriptCore
import SwiftUI
import UIKit

/// Runs a TuxSign native app: app/main.js executes in JavaScriptCore and
/// describes its UI as a tree of nodes, which NativeUI renders as real
/// SwiftUI (Liquid Glass included). Events call back into JavaScript and
/// state changes re-render.
@MainActor
@Observable
final class NativeRuntime {
    static var appDir: URL { Bundle.main.bundleURL.appendingPathComponent("app", isDirectory: true) }
    static var hasApp: Bool {
        FileManager.default.fileExists(atPath: appDir.appendingPathComponent("main.js").path)
    }

    var root: Node?
    var sheet: Node?
    var alert: AlertSpec?
    var error: String?

    let context: JSContext = JSContext()!
    let bridge = Bridge()
    @ObservationIgnored private var timers: [Int: Timer] = [:]
    @ObservationIgnored private var documents: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    init() {
        bridge.sink = { [weak self] name, payload in self?.call("__emit", [name, payload]) }
        install()
        context.evaluateScript(Bridge.apiJS + Self.prelude, withSourceURL: URL(string: "tux://prelude.js"))
        call("__boot", [])
    }

    // MARK: calling into JavaScript

    /// Calls a global JS function, then re-renders if state changed.
    @discardableResult
    func call(_ name: String, _ args: [Any]) -> JSValue? {
        let result = context.objectForKeyedSubscript(name)?.call(withArguments: args)
        if name != "__flush" { flush() }
        return result
    }

    func flush() {
        _ = context.objectForKeyedSubscript("__flush")?.call(withArguments: [])
    }

    func invoke(_ fn: Int?, _ args: [Any] = []) {
        guard let fn else { return }
        call("__invoke", [fn] + args)
    }

    func dismissSheet() { sheet = nil; call("__dismissSheet", []) }
    func dismissAlert() { alert = nil; call("__dismissAlert", []) }

    private func apply(_ payload: [String: Any]) {
        let update = {
            self.root = Node(payload["root"])
            self.sheet = Node(payload["sheet"], path: "sheet")
            self.alert = AlertSpec(payload["alert"])
        }
        if let style = payload["animation"] as? String {
            withAnimation(Self.animation(style), update)
        } else {
            update()
        }
    }

    static func animation(_ name: String) -> Animation {
        switch name {
        case "bouncy": .bouncy
        case "snappy": .snappy
        case "smooth": .smooth
        case "spring": .spring
        case "easeInOut": .easeInOut
        case "linear": .linear
        default: .default
        }
    }

    // MARK: native functions exposed to JavaScript

    private func define(_ name: String, _ block: Any) {
        context.setObject(block, forKeyedSubscript: name as NSString)
    }

    private func null() -> JSValue { JSValue(nullIn: context) }

    private func safePath(_ path: String) -> URL? {
        let url = documents.appendingPathComponent(path).standardizedFileURL
        return url.path.hasPrefix(documents.standardizedFileURL.path) ? url : nil
    }

    private func install() {
        context.exceptionHandler = { [weak self] _, exception in
            let message = exception?.toString() ?? "error"
            let stack = exception?.objectForKeyedSubscript("stack")?.toString() ?? ""
            NSLog("[js] %@\n%@", message, stack)
            MainActor.assumeIsolated { self?.error = "\(message)\n\(stack)" }
        }

        let log: @convention(block) (String) -> Void = { NSLog("[js] %@", $0) }
        define("__log", log)

        let render: @convention(block) (JSValue) -> Void = { [weak self] value in
            MainActor.assumeIsolated {
                guard let self, let payload = value.toDictionary() as? [String: Any] else { return }
                self.apply(payload)
            }
        }
        define("__render", render)

        let setTimer: @convention(block) (Int, Double, Bool) -> Void = { [weak self] id, ms, repeats in
            MainActor.assumeIsolated {
                self?.timers[id]?.invalidate()
                self?.timers[id] = Timer.scheduledTimer(withTimeInterval: max(ms, 0) / 1000, repeats: repeats) { _ in
                    MainActor.assumeIsolated {
                        if !repeats { self?.timers[id] = nil }
                        self?.call("__timer", [id])
                    }
                }
            }
        }
        define("__setTimer", setTimer)

        let clearTimer: @convention(block) (Int) -> Void = { [weak self] id in
            MainActor.assumeIsolated {
                self?.timers[id]?.invalidate()
                self?.timers[id] = nil
            }
        }
        define("__clearTimer", clearTimer)

        let tuxCall: @convention(block) (String, JSValue, JSValue, JSValue) -> Void = { [weak self] method, args, resolve, reject in
            MainActor.assumeIsolated {
                guard let self else { return }
                let dict = args.toDictionary() as? [String: Any] ?? [:]
                Task { @MainActor in
                    do {
                        let result = try await self.bridge.handle(method, dict)
                        resolve.call(withArguments: [result ?? NSNull()])
                    } catch {
                        reject.call(withArguments: [error.localizedDescription])
                    }
                    self.flush()
                }
            }
        }
        define("__tuxCall", tuxCall)

        let fetch: @convention(block) (String, JSValue, JSValue, JSValue) -> Void = { [weak self] url, opts, resolve, reject in
            MainActor.assumeIsolated {
                guard let self else { return }
                guard let u = URL(string: url) else { reject.call(withArguments: ["invalid URL: \(url)"]); return }
                let options = opts.toDictionary() as? [String: Any] ?? [:]
                var request = URLRequest(url: u)
                request.httpMethod = options["method"] as? String ?? "GET"
                for (key, value) in options["headers"] as? [String: Any] ?? [:] {
                    request.setValue("\(value)", forHTTPHeaderField: key)
                }
                if let body = options["body"] as? String { request.httpBody = Data(body.utf8) }
                Task { @MainActor in
                    do {
                        let (data, response) = try await URLSession.shared.data(for: request)
                        let http = response as? HTTPURLResponse
                        var headers: [String: String] = [:]
                        for (k, v) in http?.allHeaderFields ?? [:] { headers["\(k)".lowercased()] = "\(v)" }
                        resolve.call(withArguments: [[
                            "status": http?.statusCode ?? 0,
                            "url": response.url?.absoluteString ?? url,
                            "headers": headers,
                            "body": String(decoding: data, as: UTF8.self),
                            "base64": data.base64EncodedString(),
                        ]])
                    } catch {
                        reject.call(withArguments: [error.localizedDescription])
                    }
                    self.flush()
                }
            }
        }
        define("__fetch", fetch)

        let storageGet: @convention(block) (String) -> JSValue = { [weak self] key in
            MainActor.assumeIsolated {
                guard let self else { return JSValue() }
                guard let s = UserDefaults.standard.string(forKey: "tux." + key) else { return self.null() }
                return JSValue(object: s, in: self.context)
            }
        }
        define("__storageGet", storageGet)

        let storageSet: @convention(block) (String, JSValue) -> Void = { key, value in
            if value.isNull || value.isUndefined {
                UserDefaults.standard.removeObject(forKey: "tux." + key)
            } else {
                UserDefaults.standard.set(value.toString(), forKey: "tux." + key)
            }
        }
        define("__storageSet", storageSet)

        let fsRead: @convention(block) (String) -> JSValue = { [weak self] path in
            MainActor.assumeIsolated {
                guard let self else { return JSValue() }
                guard let url = self.safePath(path), let s = try? String(contentsOf: url, encoding: .utf8) else { return self.null() }
                return JSValue(object: s, in: self.context)
            }
        }
        define("__fsRead", fsRead)

        let fsWrite: @convention(block) (String, String) -> Bool = { [weak self] path, text in
            MainActor.assumeIsolated {
                guard let url = self?.safePath(path) else { return false }
                try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
                return (try? text.write(to: url, atomically: true, encoding: .utf8)) != nil
            }
        }
        define("__fsWrite", fsWrite)

        let fsList: @convention(block) (String) -> [String] = { [weak self] path in
            MainActor.assumeIsolated {
                guard let url = self?.safePath(path) else { return [] }
                return (try? FileManager.default.contentsOfDirectory(atPath: url.path))?.sorted() ?? []
            }
        }
        define("__fsList", fsList)

        let fsRemove: @convention(block) (String) -> Bool = { [weak self] path in
            MainActor.assumeIsolated {
                guard let url = self?.safePath(path), url != self?.documents.standardizedFileURL else { return false }
                return (try? FileManager.default.removeItem(at: url)) != nil
            }
        }
        define("__fsRemove", fsRemove)

        // Only files bundled inside the app's own app/ folder can be required.
        let readApp: @convention(block) (String) -> JSValue = { [weak self] path in
            MainActor.assumeIsolated {
                guard let self else { return JSValue() }
                let dir = Self.appDir.standardizedFileURL
                let url = dir.appendingPathComponent(path).standardizedFileURL
                guard url.path.hasPrefix(dir.path), let s = try? String(contentsOf: url, encoding: .utf8) else {
                    return self.null()
                }
                return JSValue(object: s, in: self.context)
            }
        }
        define("__readApp", readApp)
    }
}

struct AlertSpec {
    struct ButtonSpec: Identifiable {
        let id: Int
        let text: String
        let role: ButtonRole?
        let action: Int?
    }

    let title: String
    let message: String?
    let buttons: [ButtonSpec]

    init?(_ any: Any?) {
        guard let d = any as? [String: Any] else { return nil }
        title = d["title"] as? String ?? ""
        message = d["message"] as? String
        let raw = d["buttons"] as? [[String: Any]] ?? []
        buttons = raw.enumerated().map { i, b in
            ButtonSpec(id: i, text: b["text"] as? String ?? "OK", role: Props.role(b["role"]),
                       action: (b["action"] as? [String: Any])?["$fn"] as? Int)
        }
    }
}
